"""cad's support for camlib (github.com/stevecad/camlib, MIT), a native CAM engine: the planner a CAM job runs when it
names ``"planner": "camlib"``. SPIKE: the engine is imported from the environment (built from a pinned checkout; there
is no release yet), and only the LinuxCNC post is wired. What a job means is ``cad._internal.cam``'s; camlib plans,
simulates and posts, and cad's own checks read the posted program back. Nothing of the engine is re-exported."""
