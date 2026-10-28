"""The example project's standard notes by name: the texts its PMI examples write their notes from
(``note(id, NOTES[name])``, ``cad.ap242``'s), a module of the project's own code like any other.

ILLUSTRATIVE: a project's own notes in its own words, written to exercise the notes, not taken from
any shop's standard or process. text-to-cad ships no note text; a real project keeps its own here."""

NOTES = {
    "edges": "Remove all burrs and break sharp edges",
    "primer-mask": "Mask these features before coating with primer",
    # NIST's Note 1 on its PMI test models (public domain, nist_ctc_02_housing.py's source).
    "basic-from-model": "Obtain dimensions for all undimensioned features from the model. All dimensions "
                        "obtained from the model are basic unless otherwise specified",
}
