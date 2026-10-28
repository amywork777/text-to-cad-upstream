"""Edit mode: a part script read as a design, one number of it changed by hand, and modeling
commands (Fillet, Chamfer, Hole, Shell, Mirror, Pattern) written into it as lines of build123d.

``service`` runs in the viewer's server and only starts processes and passes JSON; ``tracer`` is
the process that runs the part, with the CAD kernel, and ``commands`` writes a command's line in
that process. Nothing here is imported at module scope by the viewer.
"""
