import re
from pathlib import Path
from models import LoadRecord

class E2KError(RuntimeError): pass
KV=re.compile(r'([A-Za-z0-9_./-]+)\s*=\s*("[^"]*"|[^\s]+)')
Q=re.compile(r'"([^"]*)"')

def fields(line):
    d={k.upper():(v[1:-1] if v.startswith('"') and v.endswith('"') else v) for k,v in KV.findall(line)}
    d['_Q']=Q.findall(line); return d

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
        for sec,lines in self.sections.items():
            if 'STORY' not in sec:continue
            for line in lines:
                d=fields(line); q=d['_Q']; st=pick(d,'STORY','NAME',default=(q[0] if q else None))
                if st and str(st) not in out:out.append(str(st))
        if not out:
            for lines in self.sections.values():
                for line in lines:
                    d=fields(line); st=pick(d,'STORY','STORYNAME')
                    if st and str(st) not in out:out.append(str(st))
        return out
    def _points(self):
        pts={}
        for sec,lines in self.sections.items():
            if not (('POINT' in sec or 'JOINT' in sec) and ('COORD' in sec or 'CONNECT' in sec)):continue
            for line in lines:
                d=fields(line); q=d['_Q']; name=pick(d,'POINT','JOINT','NAME',default=(q[0] if q else None)); st=pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else ''))
                x=pick(d,'X','GLOBALX');y=pick(d,'Y','GLOBALY');z=pick(d,'Z','GLOBALZ',default=0)
                if name is not None and x is not None and y is not None:
                    p=(num(x),num(y),num(z));pts[(str(name),str(st))]=p;pts[(str(name),'')]=p
        return pts
    def _areas(self,pts):
        areas={}
        for sec,lines in self.sections.items():
            if not ('AREA' in sec and ('CONNECT' in sec or 'OBJECT' in sec)):continue
            for line in lines:
                d=fields(line);q=d['_Q'];name=pick(d,'AREA','NAME',default=(q[0] if q else None));st=pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else ''))
                pn=[str(d[k]) for k in ('POINT1','POINT2','POINT3','POINT4','POINT5','POINT6','POINT7','POINT8') if k in d]
                if not pn and len(q)>2:pn=q[2:]
                poly=[pts.get((n,str(st))) or pts.get((n,'')) for n in pn];poly=[p for p in poly if p]
                if name and len(poly)>=3:areas[(str(name),str(st))]=poly
        return areas
    def _frames(self,pts):
        fr={}
        for sec,lines in self.sections.items():
            if not (('FRAME' in sec or 'LINE' in sec) and ('CONNECT' in sec or 'OBJECT' in sec)):continue
            for line in lines:
                d=fields(line);q=d['_Q'];name=pick(d,'FRAME','LINE','NAME',default=(q[0] if q else None));st=pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else ''))
                a=pick(d,'POINTI','POINT1','IEND','JOINTI');b=pick(d,'POINTJ','POINT2','JEND','JOINTJ')
                if a and b:
                    pa=pts.get((str(a),str(st))) or pts.get((str(a),''));pb=pts.get((str(b),str(st))) or pts.get((str(b),''))
                    if pa and pb and name:fr[(str(name),str(st))]=(pa,pb)
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
                d=fields(line);q=d['_Q'];st=str(pick(d,'STORY','STORYNAME',default=(q[1] if len(q)>1 else story)))
                if st!=story:continue
                pat=pick(d,'LOADPAT','LOADPATTERN','LOADCASE','CASE','PATTERN')
                if 'AREA' in sec and ('UNIFORM' in sec or 'DISTRIBUT' in sec):
                    obj=pick(d,'AREA','NAME',default=(q[0] if q else None));val=pick(d,'VALUE','LOAD','W');poly=areas.get((str(obj),story));vec=self._vec(pick(d,'DIR','DIRECTION'),val)
                    if obj and pat is not None and val is not None and poly and vec:
                        recs.append(LoadRecord('E2K',story,str(obj),str(pat),'area',[(p[0],p[1]) for p in poly],fx=vec[0],fy=vec[1],fz=vec[2]));continue
                if ('POINT' in sec or 'JOINT' in sec) and ('FORCE' in sec or 'FORCES' in sec):
                    obj=pick(d,'POINT','JOINT','NAME',default=(q[0] if q else None));p=pts.get((str(obj),story)) or pts.get((str(obj),''))
                    if obj and pat is not None and p:
                        recs.append(LoadRecord('E2K',story,str(obj),str(pat),'point',[(p[0],p[1])],fx=num(pick(d,'FX','F1')),fy=num(pick(d,'FY','F2')),fz=num(pick(d,'FZ','F3')),mx=num(pick(d,'MX','M1')),my=num(pick(d,'MY','M2'))));continue
                if ('FRAME' in sec or 'LINE' in sec) and ('DISTRIBUT' in sec or 'UNIFORM' in sec):
                    obj=pick(d,'FRAME','LINE','NAME',default=(q[0] if q else None));ab=frames.get((str(obj),story));v1=pick(d,'VAL1','VALUE1','LOAD','W','F');v2=pick(d,'VAL2','VALUE2',default=v1);vv1=self._vec(pick(d,'DIR','DIRECTION'),v1);vv2=self._vec(pick(d,'DIR','DIRECTION'),v2)
                    if obj and pat is not None and ab and v1 is not None and vv1 and vv2:
                        a,b=ab;recs.append(LoadRecord('E2K',story,str(obj),str(pat),'line',[(a[0],a[1]),(b[0],b[1])],fx=vv1[0],fy=vv1[1],fz=vv1[2],val2_fx=vv2[0],val2_fy=vv2[1],val2_fz=vv2[2]));continue
                if any(x in sec for x in ('AREA','POINT','JOINT','FRAME','LINE')):self.diagnostics['unparsed_load_lines'].append(sec+': '+line)
        if not recs:self.diagnostics['warnings'].append('No supported loads parsed. Use EDB mode for production or calibrate E2K field names from this diagnostic.')
        return recs
