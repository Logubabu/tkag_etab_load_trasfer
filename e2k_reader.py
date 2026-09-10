import re
from pathlib import Path
from models import LoadRecord

class E2KError(RuntimeError): pass
KV=re.compile(r'([A-Za-z0-9_./-]+)\s*=\s*("[^"]*"|[^\s]+)')
Q=re.compile(r'"([^"]*)"')

TOKEN_RE = re.compile(r'"([^"]*)"|([^\s]+)')

KNOWN_KEYS = {
    'STORY', 'STORYNAME', 'NAME', 'TYPE', 'DIR', 'DIRECTION', 'LC', 'LOADPAT',
    'LOADPATTERN', 'LOADCASE', 'CASE', 'PATTERN', 'VALUE', 'VAL', 'VAL1', 'VAL2',
    'VALUE1', 'VALUE2', 'FVAL', 'W', 'FX', 'FY', 'FZ', 'MX', 'MY', 'M1', 'M2', 'F1', 'F2', 'F3',
    'POINT', 'JOINT', 'AREA', 'FRAME', 'LINE', 'POINT1', 'POINT2', 'POINT3', 'POINT4',
    'X', 'Y', 'Z', 'ELEV', 'HEIGHT', 'GLOBALX', 'GLOBALY', 'GLOBALZ', 'LINELOAD', 'AREALOAD', 'POINTLOAD', 'T'
}

def fields(line):
    d = {}
    quoted = Q.findall(line)
    d['_Q'] = quoted
    
    # 1. Match explicit KEY=VAL
    for k, v in KV.findall(line):
        d[k.upper()] = v[1:-1] if v.startswith('"') and v.endswith('"') else v

    # 2. Tokenize line to extract space-separated KEY VAL pairs
    matches = TOKEN_RE.findall(line)
    tokens = [(m[0] if m[0] else m[1]) for m in matches]
    
    if tokens:
        first = tokens[0].upper()
        if first in ('AREALOAD', 'LINELOAD', 'POINTLOAD'):
            if len(quoted) >= 1: d.setdefault('NAME', quoted[0])
            if len(quoted) >= 2: d.setdefault('STORY', quoted[1])
        elif first in ('AREA', 'LINE', 'FRAME', 'POINT', 'JOINT'):
            if len(quoted) >= 1: d.setdefault('NAME', quoted[0])
    
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if '=' in t:
            parts = t.split('=', 1)
            d[parts[0].upper()] = parts[1].strip('"')
            i += 1
            continue
            
        t_upper = t.upper()
        if t_upper in KNOWN_KEYS and i + 1 < len(tokens):
            nxt = tokens[i+1]
            if nxt.upper() not in KNOWN_KEYS:
                if t_upper not in d:
                    d[t_upper] = nxt
                i += 2
                continue
        i += 1
        
    return d

def pick(d,*keys,default=None):
    for k in keys:
        if k in d:return d[k]
    return default

def num(v,default=0.0):
    try:return float(v)
    except:return default

def norm(s):return re.sub(r'[^A-Z0-9]+',' ',s.upper()).strip()

class E2KReader:
    def __init__(self,cfg): self.cfg=cfg; self.sections={}; self.diagnostics={}
    def read(self,path):
        cur='HEADER'; self.sections={cur:[]}
        for raw in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
            line=raw.strip()
            if not line:continue
            if line.startswith('$'):
                title=norm(line[1:])
                if title.startswith('END OF MODEL'):continue
                cur=title; self.sections.setdefault(cur,[]); continue
            self.sections.setdefault(cur,[]).append(line)
        self.diagnostics={'sections':list(self.sections),'warnings':[],'unparsed_load_lines':[]}
        return self
    def stories(self):
        out=[]
        # 1. Primary: Look in story definition sections
        for sec,lines in self.sections.items():
            if 'STORIES' in sec or 'STORY DATA' in sec:
                for line in lines:
                    d=fields(line); q=d['_Q']; st=pick(d,'STORY','NAME','STORYNAME',default=(q[0] if q else None))
                    if st and str(st) not in out and str(st).upper() not in ('HEIGHT','ELEV','ELEVATION'):
                        out.append(str(st))
        if not out:
            # 2. Fallback: Check lines starting with STORY
            for lines in self.sections.values():
                for line in lines:
                    if line.startswith('STORY'):
                        d=fields(line); q=d['_Q']; st=pick(d,'STORY','NAME','STORYNAME',default=(q[0] if q else None))
                        if st and str(st) not in out:out.append(str(st))
        return out

    def _points(self):
        pts={}
        for sec,lines in self.sections.items():
            if not (('POINT' in sec or 'JOINT' in sec) and ('COORD' in sec or 'CONNECT' in sec)):continue
            for line in lines:
                d=fields(line); q=d['_Q']; name=pick(d,'POINT','JOINT','NAME',default=(q[0] if q else None)); st=pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else ''))
                # Extract numeric coordinate values from unquoted parts of line
                clean_line=re.sub(r'"[^"]*"', '', line)
                nums=[float(t) for t in re.findall(r'-?\d+\.?\d*(?:[eE][+-]?\d+)?', clean_line)]
                x=pick(d,'X','GLOBALX',default=(nums[0] if len(nums)>=1 else None))
                y=pick(d,'Y','GLOBALY',default=(nums[1] if len(nums)>=2 else None))
                z=pick(d,'Z','GLOBALZ',default=(nums[2] if len(nums)>=3 else 0))
                if name is not None and x is not None and y is not None:
                    p=(num(x),num(y),num(z));pts[(str(name),str(st))]=p;pts[(str(name),'')]=p
        return pts

    def _areas(self,pts):
        areas={}
        for sec,lines in self.sections.items():
            if not (('AREA' in sec or 'SHELL' in sec) and ('CONNECT' in sec or 'OBJECT' in sec)):continue
            for line in lines:
                d=fields(line);q=d['_Q'];name=pick(d,'AREA','NAME',default=(q[0] if q else None));st=pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else ''))
                pn=[str(d[k]) for k in ('POINT1','POINT2','POINT3','POINT4','POINT5','POINT6','POINT7','POINT8') if k in d]
                if not pn and len(q)>=2:pn=q[1:]
                poly=[pts.get((n,str(st))) or pts.get((n,'')) for n in pn];poly=[p for p in poly if p]
                if name and len(poly)>=3:areas[(str(name),str(st))]=poly;areas[(str(name),'')]=poly
        return areas

    def _frames(self,pts):
        fr={}
        for sec,lines in self.sections.items():
            if not (('FRAME' in sec or 'LINE' in sec) and ('CONNECT' in sec or 'OBJECT' in sec)):continue
            for line in lines:
                d=fields(line);q=d['_Q'];name=pick(d,'FRAME','LINE','NAME',default=(q[0] if q else None));st=pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else ''))
                a=pick(d,'POINTI','POINT1','IEND','JOINTI',default=(q[1] if len(q)>=3 else (q[1] if len(q)>=2 else None)))
                b=pick(d,'POINTJ','POINT2','JEND','JOINTJ',default=(q[2] if len(q)>=3 else (q[2] if len(q)>=2 else None)))
                if a and b:
                    pa=pts.get((str(a),str(st))) or pts.get((str(a),''));pb=pts.get((str(b),str(st))) or pts.get((str(b),''))
                    if pa and pb and name:fr[(str(name),str(st))]=(pa,pb);fr[(str(name),'')]=(pa,pb)
        return fr
    def _vec(self,direction,value):
        d=str(direction or 'GRAVITY').upper();v=num(value)
        if d in ('GRAVITY','GRAV','10','11','Z-','-Z'):return (0,0,-abs(v) if v>0 else v)
        if d in ('Z','GLOBALZ','6'):return (0,0,v)
        if d in ('X','GLOBALX','4'):return (v,0,0)
        if d in ('Y','GLOBALY','5'):return (0,v,0)
        return None
    def extract_story(self,story):
        pts=self._points();areas=self._areas(pts);frames=self._frames(pts);recs=[]
        for sec,lines in self.sections.items():
            isload='LOAD' in sec
            if not isload:continue
            for line in lines:
                d=fields(line);q=d['_Q']
                st_line=pick(d,'STORY','STORYNAME')
                obj=pick(d,'AREA','FRAME','LINE','POINT','JOINT','NAME',default=(q[0] if q else None))
                if not obj: continue

                # Check if object belongs to target story
                on_target = False
                if st_line is not None:
                    on_target = (str(st_line) == story)
                else:
                    sobj = str(obj)
                    if (sobj, story) in areas or (sobj, story) in frames or (sobj, story) in pts:
                        on_target = True
                    else:
                        on_target = True

                if not on_target: continue

                pat=pick(d,'LC','LOADPAT','LOADPATTERN','LOADCASE','CASE','PATTERN',default=(q[1] if len(q)>1 and st_line is not None else (q[1] if len(q)>1 and q[0]==obj else None)))
                if not pat: continue

                # Check load types (Area, Point/Joint, Frame/Line)
                if ('AREA' in sec or 'SHELL' in sec or 'AREA' in d or 'AREALOAD' in line) and ('UNIFORM' in sec or 'UNIFF' in line or 'UNIF' in line or 'UNIFORM' in line or 'DISTRIBUT' in sec or 'FVAL' in d or 'VAL' in d or 'VALUE' in d or 'LOAD' in d or 'W' in d):
                    val=pick(d,'FVAL','VAL','VALUE','VAL1','VALUE1','LOAD','W')
                    poly=areas.get((str(obj),story)) or areas.get((str(obj),''))
                    vec=self._vec(pick(d,'DIR','DIRECTION'),val)
                    if val is not None and poly and vec:
                        recs.append(LoadRecord('E2K',story,str(obj),str(pat),'area',[(p[0],p[1]) for p in poly],fx=vec[0],fy=vec[1],fz=vec[2]));continue
                
                if ('POINT' in sec or 'JOINT' in sec or 'POINT' in d or 'JOINT' in d or 'POINTLOAD' in line) and ('FORCE' in sec or 'FORCES' in sec or 'FORCE' in line or any(k in d for k in ('FX','FY','FZ','F1','F2','F3'))):
                    p=pts.get((str(obj),story)) or pts.get((str(obj),''))
                    if p:
                        recs.append(LoadRecord('E2K',story,str(obj),str(pat),'point',[(p[0],p[1])],fx=num(pick(d,'FX','F1')),fy=num(pick(d,'FY','F2')),fz=num(pick(d,'FZ','F3')),mx=num(pick(d,'MX','M1')),my=num(pick(d,'MY','M2'))));continue
                
                if ('FRAME' in sec or 'LINE' in sec or 'FRAME' in d or 'LINE' in d or 'LINELOAD' in line) and ('DISTRIBUT' in sec or 'UNIFORM' in sec or 'UNIFF' in line or 'UNIF' in line or 'DISTRIBUT' in line or 'UNIFORM' in line or any(k in d for k in ('FVAL','VAL','VAL1','VAL2','VALUE1','VALUE2'))):
                    ab=frames.get((str(obj),story)) or frames.get((str(obj),''))
                    v1=pick(d,'FVAL','VAL','VAL1','VALUE1','LOAD','W','F')
                    v2=pick(d,'VAL2','VALUE2',default=v1)
                    vv1=self._vec(pick(d,'DIR','DIRECTION'),v1)
                    vv2=self._vec(pick(d,'DIR','DIRECTION'),v2)
                    if ab and v1 is not None and vv1 and vv2:
                        a,b=ab;recs.append(LoadRecord('E2K',story,str(obj),str(pat),'line',[(a[0],a[1]),(b[0],b[1])],fx=vv1[0],fy=vv1[1],fz=vv1[2],val2_fx=vv2[0],val2_fy=vv2[1],val2_fz=vv2[2]));continue
                
                if any(x in sec for x in ('AREA','SHELL','POINT','JOINT','FRAME','LINE')):self.diagnostics['unparsed_load_lines'].append(sec+': '+line)
        if not recs:self.diagnostics['warnings'].append('No supported loads parsed. Use EDB mode for production or calibrate E2K field names from this diagnostic.')
        return recs
