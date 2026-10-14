"""Machine models a job may name (``"machine": {"model": "tormach-1100mx"}``), and what a job that names none assumes.

A model is optional: the user may not know theirs. With one, its numbers stand in for the job's unstated machine keys
(the job's own keys still win), each from the maker's published spec page (:attr:`Model.source`); a number the maker
does not publish is left out, never guessed, and the plan then takes the generic value and says so. Without one, the
machine kind's generic values stand in (:data:`GENERIC`): the most widely read post for the kind, a spindle limit
most of its machines reach, the controller's own tapping cycle, not homed. Every value a plan takes that nobody stated is listed in its
``assumed`` (``{"key", "value", "why"}``), which the run prints, writes into the GLB and the Viewer shows under the
verdict.

A machine whose controller reads no G-code file cadgen can write (a cloud-only laser, a laser on a Ruida controller)
is in :data:`UNSUPPORTED`: naming it is a teaching refusal, not a silent fallback. Data and lookups only: stdlib, no
network, ships in the wheel.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from cadgen._internal.cam.job_errors import CamJobError, shown

__all__ = ["GENERIC", "MODELS", "Model", "UNSUPPORTED", "generic_post_why", "lookup", "model_ids"]


@dataclass(frozen=True)
class Model:
    """One machine model as its maker publishes it. A field left ``None`` is a number the maker's page does not
    give: the plan takes the generic value for it and lists it as assumed."""

    id: str
    plain: str
    maker: str
    kind: str
    #: The controller in plain words ("PathPilot (LinuxCNC)"), and the registered post that writes for it.
    controller: str
    post: str
    #: The maker's spec page the numbers come from (https).
    source: str
    #: ``[x, y, z]`` mm (a lathe ``[x, z]``, a laser or plasma ``[x, y]``).
    travel_mm: tuple[float, ...] | None = None
    min_rpm: float | None = None
    max_rpm: float | None = None
    max_feed_mm_min: float | None = None
    rapid_mm_min: float | None = None
    #: ``none`` (one tool, changed by hand between files), ``manual`` (changed by hand at a stop, a tool table),
    #: ``atc`` (an automatic changer of ``tool_capacity`` pockets or turret stations).
    tool_changer: str | None = None
    tool_capacity: int | None = None
    #: Average tool-to-tool time (s), where the maker publishes one.
    tool_change_s: float | None = None
    #: Whether the controller taps rigidly (the feed synchronised to the spindle); ``None``: not published.
    rigid_tap: bool | None = None
    #: Rotary axes the maker offers: ``("a",)`` an optional 4th axis; a five-axis model's own axes.
    rotary: tuple[str, ...] = ()
    #: A five-axis model's kinematics and rotary travel (degrees).
    kinematics: str | None = None
    rotary_limits_deg: tuple[tuple[str, float, float], ...] = ()
    #: Homing switches as standard: it homes before running, so machine coordinates mean something.
    homed: bool | None = None
    spindle_spinup_s: float | None = None
    #: A laser's source and optical power (W).
    laser_source: str | None = None
    power_w: float | None = None
    #: Anything the plain numbers do not say (an option the numbers are for, a source that is not the maker's).
    note: str = ""

    def machine_keys(self) -> dict:
        """The job's machine keys this model states (``kind``, ``post``, ``max_rpm``...), as a job would write them."""
        out = {"kind": self.kind, "post": self.post, "name": self.plain}
        for key in ("travel_mm", "min_rpm", "max_rpm", "max_feed_mm_min", "rapid_mm_min", "tool_change_s",
                    "rigid_tap", "kinematics", "spindle_spinup_s", "laser_source", "power_w"):
            value = getattr(self, key)
            if value is not None:
                out[key] = list(value) if isinstance(value, tuple) else value
        if self.rotary_limits_deg:
            out["rotary_limits_deg"] = {axis: [low, high] for axis, low, high in self.rotary_limits_deg}
        return out

    def as_dict(self) -> dict:
        out = {"id": self.id, "plain": self.plain, "maker": self.maker, "kind": self.kind,
               "controller": self.controller, "post": self.post, "source": self.source}
        for key in ("travel_mm", "min_rpm", "max_rpm", "max_feed_mm_min", "rapid_mm_min", "tool_changer",
                    "tool_capacity", "tool_change_s", "rigid_tap", "kinematics", "homed", "spindle_spinup_s",
                    "laser_source", "power_w"):
            value = getattr(self, key)
            if value is not None:
                out[key] = list(value) if isinstance(value, tuple) else value
        if self.rotary:
            out["rotary"] = list(self.rotary)
        if self.note:
            out["note"] = self.note
        return out


def _m(**kw) -> Model:
    return Model(**kw)


_HAAS = "Haas control (NGC)"

#: The catalog: popular machines across the kinds, by id. Every number is the maker's own (``source``); a model
#: whose page leaves a number out has it ``None``.
MODELS: dict[str, Model] = {model.id: model for model in (
    # --- Haas (haascnc.com model pages, metric figures) ---------------------------------------------------------
    _m(id="haas-vf-1", plain="Haas VF-1", maker="Haas", kind="mill", controller=_HAAS, post="haas",
       source="https://haascnc.com/machines/vertical-mills/vf-series/models/small/vf-1",
       travel_mm=(508.0, 406.0, 508.0), max_rpm=8100.0, max_feed_mm_min=16500.0, rapid_mm_min=25400.0,
       tool_changer="atc", tool_capacity=20, tool_change_s=4.2, rigid_tap=True, rotary=("a",)),
    _m(id="haas-vf-2", plain="Haas VF-2", maker="Haas", kind="mill", controller=_HAAS, post="haas",
       source="https://haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2",
       travel_mm=(762.0, 406.0, 508.0), max_rpm=8100.0, max_feed_mm_min=16500.0, rapid_mm_min=25400.0,
       tool_changer="atc", tool_capacity=20, tool_change_s=4.2, rigid_tap=True),
    _m(id="haas-mini-mill", plain="Haas Mini Mill", maker="Haas", kind="mill", controller=_HAAS, post="haas",
       source="https://haascnc.com/machines/vertical-mills/mini-mills/models/minimill",
       travel_mm=(406.0, 356.0, 381.0), max_rpm=8000.0, rapid_mm_min=20300.0, tool_changer="atc", tool_capacity=10,
       tool_change_s=4.2, rotary=("a",),
       note="the page's maximum cutting feed disagrees with itself (650 ipm, 6.5 m/min), so it is left out; rigid "
            "tapping is not listed as standard"),
    _m(id="haas-umc-500", plain="Haas UMC-500", maker="Haas", kind="mill5", controller=_HAAS, post="haas",
       source="https://haascnc.com/machines/vertical-mills/universal-machine/models/umc-500",
       travel_mm=(610.0, 406.0, 406.0), max_rpm=8100.0, max_feed_mm_min=16500.0, rapid_mm_min=22900.0,
       tool_changer="atc", tool_capacity=30, tool_change_s=2.8, rigid_tap=True, rotary=("b", "c"),
       kinematics="bc_head", rotary_limits_deg=(("b", -35.0, 120.0),),
       note="a B tilt over a C table that turns 360°: cadgen's bc_head kinematics; a 30+1 side-mount changer"),
    _m(id="haas-st-10", plain="Haas ST-10", maker="Haas", kind="lathe", controller=_HAAS, post="haas",
       source="https://haascnc.com/machines/lathes/st/models/standard/st-10",
       travel_mm=(200.0, 406.0), max_rpm=6000.0, rapid_mm_min=30500.0, tool_changer="atc", tool_capacity=12,
       rigid_tap=True, note="a 12-station bolt-on turret"),
    _m(id="haas-tl-1", plain="Haas TL-1", maker="Haas", kind="lathe", controller=_HAAS, post="haas",
       source="https://haascnc.com/machines/lathes/toolroom-lathe/models/tl-1",
       travel_mm=(203.0, 762.0), max_rpm=1800.0, rapid_mm_min=11400.0,
       note="a toolroom lathe: its turret or tool post is an option, so the tool change is not given"),
)}

#: Tormach machines run PathPilot, built on LinuxCNC (the linuxcnc post: G33.1 rigid tapping, G64 blending). Tormach
#: does not tell its rapid rate from its maximum feed, so the rapid is the X/Y maximum feed.
_PATHPILOT = "PathPilot (LinuxCNC)"
MODELS.update({model.id: model for model in (
    _m(id="tormach-440", plain="Tormach PCNC 440", maker="Tormach", kind="mill", controller=_PATHPILOT,
       post="linuxcnc", source="https://knowledgebase.tormach.com/pcnc-440/machine-specifications",
       travel_mm=(254.0, 158.75, 254.0), min_rpm=300.0, max_rpm=10000.0, max_feed_mm_min=3430.0,
       rapid_mm_min=3430.0, tool_changer="manual", rigid_tap=False, rotary=("a",), homed=True,
       note="tools change by hand in TTS holders (an 8-tool ATC is an option); taps by thread milling only"),
    _m(id="tormach-770mx", plain="Tormach 770MX", maker="Tormach", kind="mill", controller=_PATHPILOT,
       post="linuxcnc", source="https://tormach.com/770mx",
       travel_mm=(356.0, 191.0, 337.0), max_rpm=10000.0, max_feed_mm_min=11400.0, rapid_mm_min=11400.0,
       tool_changer="manual", rigid_tap=True, rotary=("a",), homed=True,
       note="the current EtherCAT 770MX; tools change by hand in BT30 holders (a 10-tool ATC is an option)"),
    _m(id="tormach-1100mx", plain="Tormach 1100MX", maker="Tormach", kind="mill", controller=_PATHPILOT,
       post="linuxcnc", source="https://knowledgebase.tormach.com/1100mx/machine-specifications",
       travel_mm=(457.0, 279.0, 413.0), min_rpm=70.0, max_rpm=10000.0, max_feed_mm_min=7620.0,
       rapid_mm_min=7620.0, tool_changer="manual", rigid_tap=True, rotary=("a",), homed=True,
       note="tools change by hand in BT30 holders (a 12-tool ATC is an option)"),
    _m(id="tormach-8l", plain="Tormach 8L", maker="Tormach", kind="lathe", controller=_PATHPILOT, post="linuxcnc",
       source="https://tormach.com/support/lathe/8l-lathe-technical-specifications",
       travel_mm=(114.0, 254.0), min_rpm=180.0, max_rpm=5000.0, max_feed_mm_min=3800.0, rapid_mm_min=3800.0,
       tool_changer="manual", rigid_tap=True, homed=True, note="a quick-change tool post, no turret"),
    _m(id="tormach-15l", plain="Tormach 15L Slant-PRO", maker="Tormach", kind="lathe", controller=_PATHPILOT,
       post="linuxcnc", source="https://tormach.com/support/lathe/15l-slant-pro-lathe-technical-specifications",
       travel_mm=(254.0, 305.0), min_rpm=180.0, max_rpm=3500.0, max_feed_mm_min=1520.0, rapid_mm_min=1520.0,
       rigid_tap=True, homed=True,
       note="no longer sold (2026); the 8-station turret, gang tooling and quick-change post are options"),
)})

#: Hobby and desktop machines whose makers publish them as GRBL machines. A trim router's speed is set by hand on its
#: dial (the S word does nothing): its range is the router's, and the posted speed is the dial setting to choose.
MODELS.update({model.id: model for model in (
    _m(id="shapeoko-5-pro", plain="Shapeoko 5 Pro", maker="Carbide 3D", kind="router",
       controller="Carbide 3D electronics run from Carbide Motion (GRBL)", post="grbl",
       source="https://carbide3d.com/shapeoko/shapeoko5pro-specs/",
       travel_mm=(1237.0, 1237.0, 155.0), min_rpm=12000.0, max_rpm=30000.0, tool_changer="manual", homed=True,
       note="the 4x4 (the 4x2 is 1237 x 623 mm); speeds are for the Carbide Compact Router, set by hand on its dial "
            "(the S word does nothing); the VFD spindle kit runs 8000-24000 rpm under G-code"),
    _m(id="shapeoko-4-xxl", plain="Shapeoko 4 XXL", maker="Carbide 3D", kind="router",
       controller="Carbide 3D V3 electronics, GRBL 1.1, run from Carbide Motion 5", post="grbl",
       source="https://shop.carbide3d.com/products/shapeoko4",
       travel_mm=(838.2, 838.2, 101.6), min_rpm=12000.0, max_rpm=30000.0, tool_changer="manual", homed=True,
       note="the XXL (the XL is 838.2 x 444.5 mm); speeds are for the Carbide Compact Router, set by hand on its "
            "dial (the S word does nothing)"),
    _m(id="nomad-3", plain="Carbide 3D Nomad 3", maker="Carbide 3D", kind="mill",
       controller="Carbide Motion electronics (GRBL 1.1)", post="grbl",
       source="https://shop.carbide3d.com/products/nomad-3",
       travel_mm=(203.2, 203.2, 76.2), min_rpm=9000.0, max_rpm=24000.0, tool_changer="manual", homed=True,
       note="a desktop mill: a 130 W ER-11 spindle (cutters to 7 mm); Carbide Motion handles M6 with its tool length "
            "sensor"),
    _m(id="x-carve-pro-4x4", plain="Inventables X-Carve Pro 4x4", maker="Inventables", kind="router",
       controller="Inventables controller with a built-in VFD, run from Easel (GRBL)", post="grbl",
       source="https://www.inventables.com/pages/x-carve-pro-tech-specs",
       travel_mm=(1219.2, 1219.2, 101.6), min_rpm=8000.0, max_rpm=24000.0, tool_changer="none",
       note="the 4x4 (the 4x2 is 1219.2 x 609.6 mm); a 1.5 kW VFD spindle. Inventables' own pages do not name the "
            "firmware or the homing switches: Easel's machine page gives GRBL 1.1h"),
    _m(id="longmill-mk2-30x30", plain="Sienci LongMill MK2 30x30", maker="Sienci Labs", kind="router",
       controller="Sienci LongBoard (GRBL 1.1h), run from gSender", post="grbl",
       source="https://resources.sienci.com/view/lmk2-mk2-specs/",
       travel_mm=(820.0, 868.0, 126.0), min_rpm=10000.0, max_rpm=30000.0, max_feed_mm_min=4000.0,
       tool_changer="manual", homed=False, rotary=("a",),
       note="sold 2022-2024 (the MK2.5 runs grblHAL); travel from the maker's MK2 drawing; speeds for the AutoSpin T1 "
            "router; Z feeds to 3000 mm/min; homing switches are an add-on kit"),
)})

#: Diode lasers whose makers publish them as GRBL machines (LightBurn's GRBL device, GRBL's $ settings).
MODELS.update({model.id: model for model in (
    _m(id="ortur-laser-master-3", plain="Ortur Laser Master 3", maker="Ortur", kind="laser",
       controller="Ortur ESP32 firmware (GRBL-compatible)", post="grbl",
       source="https://ortur.net/products/ortur-laser-master-3",
       travel_mm=(400.0, 400.0), max_feed_mm_min=20000.0, homed=True, laser_source="diode", power_w=10.0,
       note="the 10 W module; the 20 W and 40 W modules cut 400 x 380 mm. Homes without switches (sensorless). "
            "Check $30 with $$: the post's S runs to 1000"),
    _m(id="sculpfun-s30-pro-max", plain="Sculpfun S30 Pro Max", maker="Sculpfun", kind="laser",
       controller="Grbl_Esp32 (GRBL 1.1h-compatible)", post="grbl",
       source="https://www.sculpfun.com/products/sculpfun-s30-pro-max-laser-engraver-machine",
       travel_mm=(370.0, 360.0), homed=True, laser_source="diode", power_w=20.0,
       note="the standard frame; air assist is M8 (coolant air)"),
)})

_CARVERA = ("a Makera Carvera runs Makera's own Smoothieware-based firmware (M6 T0 picks up its probe, G28 goes to a "
            "clearance position), so cadgen's posts would not run on it as written: export the part as STEP and plan "
            "it in Makera Studio, or post it with Makera's own post")

#: Machines a job may name that cadgen cannot post for, with the sentence that says why and what to do instead.
UNSUPPORTED: dict[str, str] = {
    "langmuir-crossfire": "the Langmuir CrossFire's FireControl runs only programs from a Langmuir-approved post "
                          "(its pierce and height-sensing loops), so cadgen's plasma post would not run on it: "
                          "export the part's outline as a DXF and post it with Langmuir's post in "
                          "Fusion 360 or SheetCAM",
    "langmuir-crossfire-pro": "the Langmuir CrossFire PRO's FireControl runs only programs from a Langmuir-approved "
                              "post (its pierce and height-sensing loops), so cadgen's plasma post would not run on "
                              "it: export the part's outline as a DXF and post it with Langmuir's "
                              "post in Fusion 360 or SheetCAM",
    "glowforge": "a Glowforge runs only from Glowforge's own cloud app and reads no G-code file, so cadgen cannot "
                 "post for it: export the part's outline as a DXF and print it from the Glowforge app",
    "omtech": "an OMTech CO2 laser runs a Ruida controller, which reads Ruida's own binary files, not G-code, so "
              "cadgen cannot post for it: export the part's outline as a DXF and run it from LightBurn or RDWorks",
    "makera-carvera": _CARVERA,
    "carvera": _CARVERA,
    "bantam": "a Bantam Tools desktop mill runs a TinyG board fed only through Bantam's own software, which takes only "
              "the G55 work offset and no canned cycles, so cadgen's posts would not run on it: export the part as "
              "STEP or its outline as a DXF and plan it in Bantam Tools Milling Machine Software",
    "xtool": "xTool documents no G-code dialect for its lasers (they run from xTool Creative Space, or LightBurn's "
             "xTool device), so cadgen cannot post for one: export the part's outline as a DXF and run it from XCS "
             "or LightBurn",
}

#: What a job that names no model (and leaves a key out) runs on, per machine kind: ``(value, why)`` per key. The
#: post is the dialect most machines of the kind read; the spindle limit one most of them reach; the rapid rate and
#: tool change time only shape the cycle time.
GENERIC: dict[str, dict[str, tuple[object, str]]] = {}

_ISO_WHY = ("Fanuc's, the dialect most mill and lathe controls read (decimal points on every number, none of one "
            "controller's own extensions); check your controller reads it, or name its post or model")
_POSTS = {
    "mill": ("fanuc", _ISO_WHY), "mill4": ("fanuc", _ISO_WHY), "mill5": ("fanuc", _ISO_WHY),
    "lathe": ("fanuc", _ISO_WHY),
    "router": ("grbl", "GRBL, what most hobby routers run (Shapeoko, X-Carve, LongMill, Onefinity are GRBL or "
                       "GRBL-compatible); name the post or model if yours is not"),
    "laser": ("grbl", "GRBL, what most diode and CO2 lasers that read G-code run; name the post or model if yours "
                      "is not"),
    "plasma": ("plasma", "the plasma post, with torch height control codes as placeholders: set your controller's"),
    "waterjet": ("waterjet", "the one waterjet post cadgen has; check your controller reads it"),
    "wire_edm": ("wire_edm", "the one wire EDM post cadgen has (Fanuc-style); check your controller reads it"),
}
#: A spindle limit most machines of a kind reach, so speeds are not posted past what an unknown spindle turns.
_SPINDLE = {"mill": 8000.0, "mill4": 8000.0, "mill5": 8000.0, "router": 18000.0, "lathe": 3000.0}
#: Rapid traverse (mm/min) and tool change time (s) per kind: the cycle time's inputs.
_RAPID = {"mill": 5000.0, "mill4": 5000.0, "mill5": 8000.0, "router": 10000.0, "lathe": 6000.0, "laser": 12000.0,
          "plasma": 15000.0, "waterjet": 8000.0, "wire_edm": 1000.0}
_TOOL_CHANGE = {"mill": 10.0, "mill4": 10.0, "mill5": 8.0, "router": 30.0, "lathe": 3.0, "laser": 0.0, "plasma": 0.0,
                "waterjet": 0.0, "wire_edm": 60.0}
for _kind, (_post, _why) in _POSTS.items():
    GENERIC[_kind] = {
        "post": (_post, _why),
        "rapid_mm_min": (_RAPID[_kind], "a generic rate for the kind; it only shapes the cycle time"),
        "tool_change_s": (_TOOL_CHANGE[_kind], "a generic time for the kind; it only shapes the cycle time"),
    }
    if _kind in _SPINDLE:
        GENERIC[_kind]["max_rpm"] = (_SPINDLE[_kind], "a spindle speed most machines of the kind reach: speeds are "
                                                      "held to it, the feeds with them")
GENERIC_RIGID_TAP_WHY = ("not known whether the controller taps rigidly: a tap that does not say takes the "
                         "controller's own tapping cycle (M29 on Fanuc), which stops with an alarm on a controller "
                         "without rigid tapping; state machine.rigid_tap false, or the tap's \"rigid\": false, for a "
                         "floating holder")
GENERIC_HOMED_WHY = ("not known whether the machine homes: the post never moves in machine coordinates; state "
                     "machine.homed true if it does")


def generic_post_why(kind: str) -> str:
    return _POSTS[kind][1]


def model_ids() -> tuple[str, ...]:
    return tuple(MODELS)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def lookup(name: object, where: str = "machine.model") -> Model:
    """The model ``name`` names (its id, or its plain name in any case and spacing: ``Tormach 1100MX``), else the
    teaching refusal: an unsupported controller's sentence, or the closest ids and where the catalog is listed."""
    if not isinstance(name, str) or not name.strip():
        raise CamJobError(f"{where} names a machine model, like \"haas-vf-2\", not {shown(name)}; leave it out when "
                          "the model is not known")
    wanted = _key(name)
    for model in MODELS.values():
        if wanted in (_key(model.id), _key(model.plain)):
            return model
    for model_id, why in UNSUPPORTED.items():
        if wanted.startswith(_key(model_id)):
            raise CamJobError(f"{where} is {shown(name)}: {why}")
    close = difflib.get_close_matches(name.strip().lower(), list(MODELS) + list(UNSUPPORTED), n=3, cutoff=0.5)
    hint = f" (did you mean {', '.join(repr(c) for c in close)}?)" if close else ""
    raise CamJobError(f"{where} is {shown(name)}, which is not in cadgen's catalog{hint}; the models are "
                      f"{', '.join(MODELS)}. Leave model out and give machine.kind (and post, travel_mm, max_rpm if "
                      "known) for any other machine")
