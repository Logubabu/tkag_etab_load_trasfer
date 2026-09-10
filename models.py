from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional

@dataclass
class LoadRecord:
    source: str
    story: str
    object_name: str
    load_pattern: str
    kind: str  # area, line, point
    points: List[Tuple[float, float]]
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    mx: float = 0.0
    my: float = 0.0
    val2_fx: Optional[float] = None
    val2_fy: Optional[float] = None
    val2_fz: Optional[float] = None
    supported: bool = True
    warning: str = ""

    def to_dict(self):
        return asdict(self)
