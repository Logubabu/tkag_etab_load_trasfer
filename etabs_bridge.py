import math, os, sys, platform, traceback
from typing import List
from models import LoadRecord

try:
    import win32com.client
except Exception:
    win32com = None

try:
    import comtypes.client
except Exception:
    comtypes = None

class EtabsError(RuntimeError):
    pass

def _ret_tuple(value):
    return value if isinstance(value, tuple) else (value,)

def _strip_ret(v):
    """
    Normalize CSI COM output.

    Important:
    Python ETABS COM calls commonly expose ByRef outputs directly, e.g.
        GetNameListOnStory -> (NumberNames, Names)
        GetLoadUniform     -> (NumberItems, AreaName, LoadPat, CSys, Dir, Value)

    Therefore the FIRST integer must NOT be interpreted as the API return code.
    Some wrappers may append the COM HRESULT/API return code as the LAST value;
    only that trailing value is stripped when it is clearly an integer status.
    """
    t = _ret_tuple(v)
    if len(t) >= 2 and isinstance(t[-1], int):
        # Avoid stripping legitimate integer output when the whole result is
        # simply (count, array) -- last item there is an array, not int.
        return int(t[-1]), t[:-1]
    return 0, t

def _names_from_call(v):
    ret, out = _strip_ret(v)
    if ret != 0:
        return []
    for x in reversed(out):
        if isinstance(x, (tuple, list)) and (not x or isinstance(x[0], str)):
            return list(x)
    return []

def _xy_transform(x, y, cfg):
    tr = cfg["coordinate_transform"]
    x -= float(tr.get("origin_x_m", 0.0))
    y -= float(tr.get("origin_y_m", 0.0))
    if tr.get("mirror_x"): x = -x
    if tr.get("mirror_y"): y = -y
    a = math.radians(float(tr.get("rotation_deg", 0.0)))
    ca, sa = math.cos(a), math.sin(a)
    return (ca*x - sa*y, sa*x + ca*y)

def _cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

def _unit(v):
    n = math.sqrt(sum(q*q for q in v))
    return tuple(q/n for q in v) if n else (0,0,1)

class EtabsBridge:
    def __init__(self, cfg):
        self.cfg = cfg
        self.etabs = None
        self.sap = None
        self.connection_method = ""
        self.connection_log = []

    def _log(self, msg):
        self.connection_log.append(msg)

    def diagnostics(self):
        return {
            "python": sys.version,
            "python_bitness": platform.architecture()[0],
            "platform": platform.platform(),
            "pywin32_available": win32com is not None,
            "comtypes_available": comtypes is not None,
            "connection_method": self.connection_method,
            "log": self.connection_log,
        }

    def _set_model(self, obj, method):
        if obj is None:
            raise RuntimeError("ETABS object is None")
        sap = obj.SapModel
        # Test that the COM object is alive.
        try:
            sap.GetModelFilename()
        except Exception:
            pass
        self.etabs = obj
        self.sap = sap
        self.connection_method = method
        self._log("CONNECTED using " + method)
        return True

    def _attach_pywin32_active(self):
        if win32com is None:
            raise RuntimeError("pywin32 unavailable")
        obj = win32com.client.GetActiveObject("CSI.ETABS.API.ETABSObject")
        return self._set_model(obj, "pywin32 GetActiveObject")

    def _helper_pywin32_attach(self):
        if win32com is None:
            raise RuntimeError("pywin32 unavailable")
        helper = win32com.client.Dispatch("ETABSv1.Helper")
        obj = helper.GetObject("CSI.ETABS.API.ETABSObject")
        return self._set_model(obj, "ETABSv1.Helper.GetObject via pywin32")

    def _helper_pywin32_start(self):
        if win32com is None:
            raise RuntimeError("pywin32 unavailable")
        helper = win32com.client.Dispatch("ETABSv1.Helper")
        obj = helper.CreateObjectProgID("CSI.ETABS.API.ETABSObject")
        if obj is None:
            raise RuntimeError("Helper.CreateObjectProgID returned None")
        ret = obj.ApplicationStart()
        if isinstance(ret, int) and ret != 0:
            raise RuntimeError(f"ApplicationStart returned {ret}")
        return self._set_model(obj, "ETABSv1.Helper.CreateObjectProgID via pywin32")

    def _helper_comtypes_attach(self):
        if comtypes is None:
            raise RuntimeError("comtypes unavailable")
        helper = comtypes.client.CreateObject("ETABSv1.Helper")
        obj = helper.GetObject("CSI.ETABS.API.ETABSObject")
        return self._set_model(obj, "ETABSv1.Helper.GetObject via comtypes")

    def _helper_comtypes_start(self):
        if comtypes is None:
            raise RuntimeError("comtypes unavailable")
        helper = comtypes.client.CreateObject("ETABSv1.Helper")
        obj = helper.CreateObjectProgID("CSI.ETABS.API.ETABSObject")
        if obj is None:
            raise RuntimeError("Helper.CreateObjectProgID returned None")
        ret = obj.ApplicationStart()
        if isinstance(ret, int) and ret != 0:
            raise RuntimeError(f"ApplicationStart returned {ret}")
        return self._set_model(obj, "ETABSv1.Helper.CreateObjectProgID via comtypes")

    def _legacy_pywin32_start(self):
        if win32com is None:
            raise RuntimeError("pywin32 unavailable")
        obj = win32com.client.Dispatch("CSI.ETABS.API.ETABSObject")
        ret = obj.ApplicationStart()
        if isinstance(ret, int) and ret != 0:
            raise RuntimeError(f"ApplicationStart returned {ret}")
        return self._set_model(obj, "legacy direct ProgID via pywin32")

    def connect(self, start_if_needed=True):
        self.connection_log = []
        attempts = [
            ("Attach active ETABS with pywin32", self._attach_pywin32_active),
            ("Attach active ETABS with ETABSv1.Helper/pywin32", self._helper_pywin32_attach),
            ("Attach active ETABS with ETABSv1.Helper/comtypes", self._helper_comtypes_attach),
        ]
        if start_if_needed:
            attempts += [
                ("Start ETABS with ETABSv1.Helper/pywin32", self._helper_pywin32_start),
                ("Start ETABS with ETABSv1.Helper/comtypes", self._helper_comtypes_start),
                ("Start ETABS with legacy ProgID/pywin32", self._legacy_pywin32_start),
            ]
        last = None
        for name, fn in attempts:
            try:
                self._log("TRY: " + name)
                fn()
                ret = self.sap.SetPresentUnits(int(self.cfg["etabs"].get("units_enum", 6)))
                if isinstance(ret, int) and ret != 0:
                    self._log(f"WARNING: SetPresentUnits returned {ret}")
                else:
                    self._log("API units set to kN-m-C")
                return True
            except Exception as e:
                last = e
                self._log("FAILED: " + name + " -> " + repr(e))
                self.etabs = None
                self.sap = None
        raise EtabsError(
            "ETABS API connection failed.\n\n"
            + "\n".join(self.connection_log)
            + "\n\nMost common causes:\n"
              "1) Python bitness does not match ETABS (normally both should be 64-bit).\n"
              "2) ETABS API COM registration is missing/corrupt.\n"
              "3) ETABS and this tool are running at different Windows privilege levels.\n"
              "4) ETABS version/install is incomplete.\n"
              "5) pywin32/comtypes was not installed in the Python used by RUN_TOOL.bat."
        )

    def attach(self, start_if_needed=False):
        return self.connect(start_if_needed=start_if_needed)

    def open_edb_direct(self, edb_path):
        edb_path = os.path.abspath(str(edb_path))
        if not os.path.isfile(edb_path):
            raise EtabsError("EDB file not found: " + edb_path)
        if self.sap is None:
            self.connect(start_if_needed=True)
        self._log("OPEN EDB: " + edb_path)
        ret = self.sap.File.OpenFile(edb_path)
        if isinstance(ret, int) and ret != 0:
            raise EtabsError(f"Connected to ETABS, but File.OpenFile returned {ret} for:\n{edb_path}")
        self.sap.SetPresentUnits(int(self.cfg["etabs"].get("units_enum", 6)))
        return True

    def open_model(self, edb_path):
        return self.open_edb_direct(edb_path)

    def _call_get_names_on_story(self, obj_api, story):
        """
        Supports both Python-friendly CSI wrappers and wrappers that still
        require explicit ByRef placeholder arguments.
        """
        errors = []
        for args in ((story,), (story, 0, [])):
            try:
                raw = obj_api.GetNameListOnStory(*args)
                ret, out = _strip_ret(raw)
                # Python COM most often returns (NumberNames, Names)
                names = None
                count = None
                for x in out:
                    if isinstance(x, int) and count is None:
                        count = int(x)
                    elif isinstance(x, (tuple, list)) and (not x or isinstance(x[0], str)):
                        names = list(x)
                if names is not None:
                    return names
            except Exception as e:
                errors.append(repr(e))
        self._log(f"GetNameListOnStory({story}) failed: " + " | ".join(errors))
        return []

    def _call_with_ref_fallback(self, method, compact_args, explicit_args):
        """
        Try the Python COM compact call first; if the installed ETABS wrapper
        requires ByRef placeholders, retry with the full argument list.
        """
        e1 = None
        try:
            return method(*compact_args)
        except Exception as e:
            e1 = e
        try:
            return method(*explicit_args)
        except Exception as e2:
            raise RuntimeError(f"compact={e1!r}; explicit={e2!r}")

    def story_object_counts(self, story):
        areas = self._call_get_names_on_story(self.sap.AreaObj, story)
        frames = self._call_get_names_on_story(self.sap.FrameObj, story)
        points = self._call_get_names_on_story(self.sap.PointObj, story)
        return {"areas": len(areas), "frames": len(frames), "points": len(points)}

    def stories(self):
        try:
            raw = self._call_with_ref_fallback(
                self.sap.Story.GetStories,
                (),
                (0, [], [], [], [], [], [], [], [], [], [])
            )
            ret, out = _strip_ret(raw)
            candidates=[]
            for x in out:
                if isinstance(x, (tuple, list)) and x and isinstance(x[0], str):
                    candidates.append(list(x))
            if candidates:
                return candidates[0]
        except Exception as e:
            self._log("Story.GetStories failed: " + repr(e))
        raise EtabsError("Connected to ETABS, but could not read the story list.")

    def _point_xyz(self, point_name):
        try:
            raw = self._call_with_ref_fallback(
                self.sap.PointObj.GetCoordCartesian,
                (point_name,),
                (point_name, 0.0, 0.0, 0.0, "Global")
            )
            ret, out = _strip_ret(raw)
            nums = [x for x in out if isinstance(x, (float,int))]
            if len(nums) >= 3:
                return float(nums[0]), float(nums[1]), float(nums[2])
        except Exception:
            pass
        raise EtabsError(f"Could not read coordinates for point {point_name}")

    def _area_points3d(self, area_name):
        raw = self._call_with_ref_fallback(
            self.sap.AreaObj.GetPoints,
            (area_name,),
            (area_name, 0, [])
        )
        ret, out = _strip_ret(raw)
        names = []
        for x in out:
            if isinstance(x, (tuple,list)) and (not x or isinstance(x[0], str)):
                names = list(x)
        return [self._point_xyz(n) for n in names]

    def _frame_endpoints3d(self, frame_name):
        raw = self._call_with_ref_fallback(
            self.sap.FrameObj.GetPoints,
            (frame_name,),
            (frame_name, "", "")
        )
        ret, out = _strip_ret(raw)
        names = []
        for x in out:
            if isinstance(x, (tuple,list)) and len(x) >= 2:
                names = list(x)
        if not names and len(out) >= 2 and all(isinstance(x,str) for x in out[:2]):
            names = list(out[:2])
        if len(names) < 2:
            raise EtabsError(f"Could not read endpoints for frame {frame_name}")
        return self._point_xyz(names[0]), self._point_xyz(names[1])

    def _vector_for_dir(self, dir_code, csys, polygon3d=None):
        cs = (csys or "").lower()
        d = int(dir_code)
        if cs == "global":
            if d == 4: return (1,0,0)
            if d == 5: return (0,1,0)
            if d == 6: return (0,0,1)
            if d in (10,11): return (0,0,-1)
        if cs == "local" and polygon3d and d == 3 and len(polygon3d) >= 3:
            a = tuple(polygon3d[1][i]-polygon3d[0][i] for i in range(3))
            b = tuple(polygon3d[2][i]-polygon3d[0][i] for i in range(3))
            return _unit(_cross(a,b))
        return None

    def extract_story(self, story: str) -> List[LoadRecord]:
        recs = []
        area_names = self._call_get_names_on_story(self.sap.AreaObj, story)
        frame_names = self._call_get_names_on_story(self.sap.FrameObj, story)
        point_names = self._call_get_names_on_story(self.sap.PointObj, story)
        self._log(f"STORY {story}: areas={len(area_names)}, frames={len(frame_names)}, points={len(point_names)}")

        if self.cfg["etabs"].get("include_area_uniform", True):
            for name in area_names:
                poly3 = self._area_points3d(name)
                poly2 = [_xy_transform(p[0], p[1], self.cfg) for p in poly3]
                try:
                    raw = self._call_with_ref_fallback(
                        self.sap.AreaObj.GetLoadUniform,
                        (name,),
                        (name, 0, [], [], [], [], [])
                    )
                    ret, out = _strip_ret(raw)
                    if ret != 0: continue
                    arrays = [x for x in out if isinstance(x,(tuple,list))]
                    sarr = [list(x) for x in arrays if (not x or isinstance(x[0],str))]
                    narr = [list(x) for x in arrays if x and isinstance(x[0],(int,float))]
                    if len(sarr) >= 3 and len(narr) >= 2:
                        loadp, csy = sarr[-2], sarr[-1]
                        dirs, vals = narr[-2], narr[-1]
                        for pat, cs, d, val in zip(loadp,csy,dirs,vals):
                            vec = self._vector_for_dir(d, cs, poly3)
                            if vec is None:
                                recs.append(LoadRecord("ETABS",story,name,pat,"area",poly2,
                                    supported=False, warning=f"Unsupported area load direction {d} / CSys {cs}"))
                            else:
                                recs.append(LoadRecord("ETABS",story,name,pat,"area",poly2,
                                    fx=float(val)*vec[0], fy=float(val)*vec[1], fz=float(val)*vec[2]))
                except Exception as e:
                    recs.append(LoadRecord("ETABS",story,name,"","area",poly2,
                        supported=False, warning="Area load read failed: "+str(e)))

        if self.cfg["etabs"].get("include_frame_distributed", True):
            for name in frame_names:
                p0, p1 = self._frame_endpoints3d(name)
                length = math.dist(p0,p1)
                if length <= 1e-12: continue
                try:
                    raw = self._call_with_ref_fallback(
                        self.sap.FrameObj.GetLoadDistributed,
                        (name,),
                        (name, 0, [], [], [], [], [], [], [], [], [], [], [])
                    )
                    ret, out = _strip_ret(raw)
                    if ret != 0: continue
                    arrays = [x for x in out if isinstance(x,(tuple,list))]
                    sarr = [list(x) for x in arrays if (not x or isinstance(x[0],str))]
                    narr = [list(x) for x in arrays if x and isinstance(x[0],(int,float))]
                    if len(sarr) >= 3 and len(narr) >= 8:
                        loadp, csy = sarr[-2], sarr[-1]
                        mytype, dirs = narr[0], narr[1]
                        dist1, dist2, val1, val2 = narr[-4], narr[-3], narr[-2], narr[-1]
                        for pat, mt, cs, d, da, db, va, vb in zip(loadp,mytype,csy,dirs,dist1,dist2,val1,val2):
                            if int(mt) != 1:
                                recs.append(LoadRecord("ETABS",story,name,pat,"line",[],
                                    supported=False, warning="Frame distributed moment load requires manual review"))
                                continue
                            ta, tb = max(0,min(1,float(da)/length)), max(0,min(1,float(db)/length))
                            a3 = tuple(p0[i]+ta*(p1[i]-p0[i]) for i in range(3))
                            b3 = tuple(p0[i]+tb*(p1[i]-p0[i]) for i in range(3))
                            a2,b2 = _xy_transform(a3[0],a3[1],self.cfg), _xy_transform(b3[0],b3[1],self.cfg)
                            vec = self._vector_for_dir(d, cs)
                            if vec is None:
                                recs.append(LoadRecord("ETABS",story,name,pat,"line",[a2,b2],
                                    supported=False, warning=f"Unsupported line load direction {d} / CSys {cs}"))
                            else:
                                recs.append(LoadRecord("ETABS",story,name,pat,"line",[a2,b2],
                                    fx=float(va)*vec[0],fy=float(va)*vec[1],fz=float(va)*vec[2],
                                    val2_fx=float(vb)*vec[0],val2_fy=float(vb)*vec[1],val2_fz=float(vb)*vec[2]))
                except Exception as e:
                    recs.append(LoadRecord("ETABS",story,name,"","line",[],
                        supported=False, warning="Line load read failed: "+str(e)))

        if self.cfg["etabs"].get("include_joint_point", True):
            for name in point_names:
                x,y,z = self._point_xyz(name)
                xy = _xy_transform(x,y,self.cfg)
                try:
                    raw = self._call_with_ref_fallback(
                        self.sap.PointObj.GetLoadForce,
                        (name,),
                        (name, 0, [], [], [], [], [], [], [], [], [], [])
                    )
                    ret, out = _strip_ret(raw)
                    if ret != 0: continue
                    arrays = [x for x in out if isinstance(x,(tuple,list))]
                    sarr = [list(x) for x in arrays if (not x or isinstance(x[0],str))]
                    narr = [list(x) for x in arrays if x and isinstance(x[0],(int,float))]
                    if len(sarr) >= 3 and len(narr) >= 7:
                        loadp, csy = sarr[-2], sarr[-1]
                        f1,f2,f3,m1,m2,m3 = narr[-6:]
                        for pat,cs,a,b,c,d,e,f in zip(loadp,csy,f1,f2,f3,m1,m2,m3):
                            supported = (str(cs).lower()=="global")
                            recs.append(LoadRecord("ETABS",story,name,pat,"point",[xy],
                                fx=float(a),fy=float(b),fz=float(c),mx=float(d),my=float(e),
                                supported=supported,
                                warning="" if supported else f"Point load CSys {cs} is not Global; review axes."))
                except Exception as e:
                    recs.append(LoadRecord("ETABS",story,name,"","point",[xy],
                        supported=False, warning="Point load read failed: "+str(e)))

        if self.cfg["etabs"].get("include_frame_point", True):
            for name in frame_names:
                p0,p1 = self._frame_endpoints3d(name)
                length = math.dist(p0,p1)
                if length <= 1e-12: continue
                try:
                    raw = self._call_with_ref_fallback(
                        self.sap.FrameObj.GetLoadPoint,
                        (name,),
                        (name, 0, [], [], [], [], [], [], [], [])
                    )
                    ret, out = _strip_ret(raw)
                    if ret != 0: continue
                    arrays = [x for x in out if isinstance(x,(tuple,list))]
                    sarr = [list(x) for x in arrays if (not x or isinstance(x[0],str))]
                    narr = [list(x) for x in arrays if x and isinstance(x[0],(int,float))]
                    if len(sarr)>=3 and len(narr)>=4:
                        loadp,csy=sarr[-2],sarr[-1]
                        mytype,dirs,dist,vals=narr[0],narr[1],narr[-2],narr[-1]
                        for pat,mt,cs,d,di,val in zip(loadp,mytype,csy,dirs,dist,vals):
                            t=max(0,min(1,float(di)/length))
                            p=tuple(p0[i]+t*(p1[i]-p0[i]) for i in range(3))
                            xy=_xy_transform(p[0],p[1],self.cfg)
                            vec=self._vector_for_dir(d,cs)
                            if int(mt)!=1 or vec is None:
                                recs.append(LoadRecord("ETABS",story,name,pat,"point",[xy],
                                    supported=False,warning=f"Unsupported frame point load type/direction {mt}/{d} CSys {cs}"))
                            else:
                                recs.append(LoadRecord("ETABS",story,name,pat,"point",[xy],
                                    fx=float(val)*vec[0],fy=float(val)*vec[1],fz=float(val)*vec[2]))
                except Exception:
                    pass
        return recs
