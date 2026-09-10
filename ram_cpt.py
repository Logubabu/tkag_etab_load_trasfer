import sqlite3, shutil, re, math, hashlib
from pathlib import Path

class RamCptError(RuntimeError):
    pass

def _fmt_num(v):
    if abs(v) < 5e-12: v = 0.0
    if float(v).is_integer(): return str(int(v))
    return ("%.9f" % v).rstrip("0").rstrip(".")

def _pt(x,y,scale):
    return f"[{_fmt_num(x*scale)}][{_fmt_num(y*scale)}]"

def _multipoint(points,scale):
    return "".join(f"[{_pt(x,y,scale)}]" for x,y in points)

def loading_type_map(conn):
    return {r[0]: (r[1],r[2]) for r in conn.execute(
        "select LoadingType, UID, Name from LoadingLayer")}

def _category_uid(conn, layer_uid, kind):
    row = conn.execute("select UID from LoadingLevel where ParentUID=? order by UID limit 1",(layer_uid,)).fetchone()
    if not row:
        raise RamCptError(f"No LoadingLevel found for layer UID {layer_uid}")
    level_uid=row[0]
    table={"point":"PointLoadCategory","line":"LineLoadCategory","area":"AreaLoadCategory"}[kind]
    row=conn.execute(f"select UID from {table} where ParentUID=? order by UID limit 1",(level_uid,)).fetchone()
    if not row:
        raise RamCptError(f"No {table} under loading level {level_uid}")
    return row[0]

def resolve_mapping(pattern, cfg):
    for rule in cfg.get("mapping_rules",[]):
        if re.search(rule["match"], pattern or ""):
            return rule.get("action","transfer"), rule.get("ram_loading_type","other_dead"), rule
    return cfg.get("unmatched_pattern_action","review"), cfg.get("default_unmatched_ram_loading_type","other_dead"), None

def inspect_template(path):
    c=sqlite3.connect(path)
    try:
        rows=c.execute("select LoadingType,Name from LoadingLayer order by UID").fetchall()
        units=dict(c.execute("select Name,Unit from UnitHolder").fetchall())
        return {"layers":rows,"units":units,"tables":c.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]}
    finally:c.close()

def _next_uid(conn):
    maxes=[]
    for (t,) in conn.execute("select name from sqlite_master where type='table'"):
        cols=[r[1] for r in conn.execute(f"pragma table_info([{t}])")]
        if "UID" in cols:
            try:
                m=conn.execute(f"select max(UID) from [{t}]").fetchone()[0]
                if m is not None:maxes.append(int(m))
            except: pass
    return (max(maxes) if maxes else 1000)+1

def _next_child(conn, table, parent_uid):
    rows=conn.execute(f"select UID,ChildIndex from {table} where ParentUID=? order by ChildIndex,UID",(parent_uid,)).fetchall()
    prev=rows[-1][0] if rows else 0
    idx=(rows[-1][1]+1) if rows else 0
    return prev,idx

def _append_sibling(conn, table, prev_uid, new_uid):
    if prev_uid:
        conn.execute(f"update {table} set NextSibUID=? where UID=?",(new_uid,prev_uid))

def _sig(rec, target_type):
    pts=tuple((round(x,3),round(y,3)) for x,y in rec.points)
    vals=tuple(round(float(v or 0),5) for v in [rec.fx,rec.fy,rec.fz,rec.mx,rec.my,rec.val2_fx,rec.val2_fy,rec.val2_fz])
    return (target_type,rec.kind,pts,vals)

def write_copy(template_path, output_path, records, cfg, include_reviewed_unmatched=False):
    template_path=Path(template_path); output_path=Path(output_path)
    if template_path.resolve()==output_path.resolve():
        raise RamCptError("Output must be a copy, not the original CPT.")
    shutil.copy2(template_path,output_path)
    c=sqlite3.connect(output_path)
    c.execute("PRAGMA foreign_keys=OFF")
    layers=loading_type_map(c)
    scale=float(cfg["ram"]["length_per_m"])
    pf=float(cfg["ram"]["force_per_kN"])
    lf=float(cfg["ram"]["line_force_per_kN_per_m"])
    af=float(cfg["ram"]["area_force_per_kN_per_m2"])
    mf=float(cfg["ram"]["moment_per_kNm"])
    uid=_next_uid(c)
    report={"written":0,"skipped":0,"review":0,"unsupported":0,"duplicates":0,"by_pattern":{},"warnings":[]}
    seen=set()
    try:
        c.execute("BEGIN")
        for rec in records:
            report["by_pattern"].setdefault(rec.load_pattern,{"written":0,"skipped":0,"review":0})
            if not rec.supported:
                report["unsupported"]+=1
                report["warnings"].append(f"{rec.story} {rec.object_name}: {rec.warning}")
                continue
            action,target_type,_=resolve_mapping(rec.load_pattern,cfg)
            if action=="skip":
                report["skipped"]+=1; report["by_pattern"][rec.load_pattern]["skipped"]+=1; continue
            if action=="review" and not include_reviewed_unmatched:
                report["review"]+=1; report["by_pattern"][rec.load_pattern]["review"]+=1; continue
            if target_type not in layers:
                report["review"]+=1
                report["warnings"].append(f"{rec.load_pattern}: target RAM loading type '{target_type}' not present in CPT.")
                continue
            sig=_sig(rec,target_type)
            if sig in seen:
                report["duplicates"]+=1; continue
            seen.add(sig)
            layer_uid=layers[target_type][0]
            cat=_category_uid(c,layer_uid,rec.kind)
            if rec.kind=="point":
                if len(rec.points)!=1: continue
                prev,idx=_next_child(c,"PointLoad",cat)
                row=(uid,cat,prev,0,idx,f"ETABS:{rec.load_pattern}:{rec.object_name}",idx,0,0.0,"",
                     _pt(rec.points[0][0],rec.points[0][1],scale),
                     rec.fx*pf,rec.fy*pf,rec.fz*pf,rec.mx*mf,rec.my*mf)
                c.execute("""insert into PointLoad
                    (UID,ParentUID,PreviousSibUID,NextSibUID,ChildIndex,Name,Number,RssUid,LoadElevation,IsmId,
                     Point0,PLFx,PLFy,PLFz,PLMx,PLMy) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",row)
                _append_sibling(c,"PointLoad",prev,uid)
            elif rec.kind=="line":
                if len(rec.points)!=2: continue
                prev,idx=_next_child(c,"LineLoad",cat)
                fx2=rec.fx if rec.val2_fx is None else rec.val2_fx
                fy2=rec.fy if rec.val2_fy is None else rec.val2_fy
                fz2=rec.fz if rec.val2_fz is None else rec.val2_fz
                row=(uid,cat,prev,0,idx,f"ETABS:{rec.load_pattern}:{rec.object_name}",idx,0,0.0,"",
                     _pt(*rec.points[0],scale),_pt(*rec.points[1],scale),
                     rec.fx*lf,rec.fy*lf,rec.fz*lf,0.0,0.0,
                     fx2*lf,fy2*lf,fz2*lf,0.0,0.0)
                c.execute("""insert into LineLoad
                    (UID,ParentUID,PreviousSibUID,NextSibUID,ChildIndex,Name,Number,RssUid,LoadElevation,IsmId,
                    Point0,Point1,LLFx0,LLFy0,LLFz0,LLMx0,LLMy0,LLFx1,LLFy1,LLFz1,LLMx1,LLMy1)
                    values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",row)
                _append_sibling(c,"LineLoad",prev,uid)
            elif rec.kind=="area":
                if len(rec.points)<3: continue
                prev,idx=_next_child(c,"AreaLoad",cat)
                row=(uid,cat,prev,0,idx,f"ETABS:{rec.load_pattern}:{rec.object_name}",idx,0,0.0,"",
                     rec.fx*af,rec.fy*af,rec.fz*af,0.0,0.0,
                     rec.fx*af,rec.fy*af,rec.fz*af,0.0,0.0,
                     rec.fx*af,rec.fy*af,rec.fz*af,0.0,0.0,
                     _multipoint(rec.points,scale))
                c.execute("""insert into AreaLoad
                    (UID,ParentUID,PreviousSibUID,NextSibUID,ChildIndex,Name,Number,RssUid,LoadElevation,IsmId,
                     ALFx0,ALFy0,ALFz0,ALMx0,ALMy0,ALFx1,ALFy1,ALFz1,ALMx1,ALMy1,
                     ALFx2,ALFy2,ALFz2,ALMx2,ALMy2,MultiPoint)
                    values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",row)
                _append_sibling(c,"AreaLoad",prev,uid)
            else:
                continue
            uid+=1
            report["written"]+=1; report["by_pattern"][rec.load_pattern]["written"]+=1
        c.commit()
        # quick structural sanity checks
        for t in ("PointLoad","LineLoad","AreaLoad"):
            c.execute(f"select count(*) from {t}").fetchone()
        integrity=c.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok":
            raise RamCptError("SQLite integrity check failed: "+str(integrity))
    except Exception:
        c.rollback()
        c.close()
        try: output_path.unlink()
        except: pass
        raise
    c.close()
    return report
