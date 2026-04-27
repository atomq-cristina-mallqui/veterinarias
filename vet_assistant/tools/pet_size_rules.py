"""Reglas de mapeo especie + peso → tamaño de mascota.

Estas reglas también viven en los prompts (para que el LLM las verbalice), pero la
implementación canónica vive aquí porque la columna `pets.size` se computa en código
para no depender del LLM al persistir.

Reglas:
- Gato: siempre `small`.
- Perro:
    - small : peso < 10 kg
    - medium: 10 ≤ peso < 25 kg
    - large : peso ≥ 25 kg
- Otro: si no hay tamaño explícito, devolvemos None y el agente debe preguntarlo.
"""
from __future__ import annotations

from typing import Literal, Optional

PetSize = Literal["small", "medium", "large"]
Species = Literal["dog", "cat", "other"]


def derive_pet_size(species: Species, weight_kg: Optional[float]) -> Optional[PetSize]:
    """Calcula el tamaño canónico para registro en BD.

    Retorna None si no es determinable (ej. especie 'other' sin peso aclarado).
    """
    if species == "cat":
        return "small"
    if species == "dog":
        if weight_kg is None:
            return None
        if weight_kg < 10:
            return "small"
        if weight_kg < 25:
            return "medium"
        return "large"
    return None


def is_grooming_compatible_size(size: Optional[PetSize]) -> bool:
    """Útil al validar que se puede cobrar baño/peluquería: requiere tamaño definido."""
    return size in ("small", "medium", "large")
