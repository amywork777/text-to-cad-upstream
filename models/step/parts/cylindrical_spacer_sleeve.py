from cadgen import step
# Prompt: Cylindrical spacer sleeve with a central through-bore and rounded rim edges.

from simple_model_library import make_cylindrical_spacer_sleeve


@step
def cylindrical_spacer_sleeve():
    return make_cylindrical_spacer_sleeve()
