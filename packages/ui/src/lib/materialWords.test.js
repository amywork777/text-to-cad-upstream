import assert from "node:assert/strict";
import test from "node:test";

import { materialWords } from "./materialWords.js";

test("a catalogue material reads as an engineer names it", () => {
  const said = {
    Alu_G6061_T6: "Aluminum 6061-T6",
    Alu_G5052_H32: "Aluminum 5052-H32",
    Alu_ALSI10MG_AS_BUILT: "Aluminum AlSi10Mg, as built",
    MildSteel_GA36_HOT_ROLLED: "Mild steel A36, hot rolled",
    MildSteel_PLAIN_CARBON_GENERIC: "Mild steel, plain carbon",
    "AlloySteel.G52100_HARDENED_LOW_TEMPERED": "Alloy steel 52100, hardened low tempered",
    Stainless_G304_ANNEALED: "Stainless steel 304, annealed",
    Brass_C360_HALF_HARD: "Brass C360, half hard",
    Titanium_GR5_ANNEALED: "Titanium grade 5, annealed",
    Nylon_PA12_GF35: "Nylon PA12 GF35",
    TPU_SHORE_95A: "TPU Shore 95A",
    PLA_GENERIC: "PLA",
    PETG_CF: "PETG CF",
    FR4_GENERIC: "FR-4",
    Peek_MOLDED: "PEEK, molded",
    Hardwood_OAK: "Hardwood, oak",
  };
  for (const [name, words] of Object.entries(said)) assert.equal(materialWords(name), words, name);
});

test("a name written as an id reads as words; one already in words, or none, is kept", () => {
  assert.equal(materialWords("steel-g90-galvanised"), "Steel G90 galvanised");
  assert.equal(materialWords("zinc_plated_clear"), "Zinc plated clear");
  assert.equal(materialWords("Mild steel, zinc plated clear"), "Mild steel, zinc plated clear");
  assert.equal(materialWords("Custom"), "Custom");
  assert.equal(materialWords("6061-T6"), "6061-T6");
  assert.equal(materialWords(""), "");
  assert.equal(materialWords(undefined), "");
});
