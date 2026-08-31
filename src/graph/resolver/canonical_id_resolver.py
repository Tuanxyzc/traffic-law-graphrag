import re
import unicodedata

class CanonicalIDResolver:
    """
    Centralized resolver for ID canonicalization.
    This class is the SINGLE SOURCE OF TRUTH for converting raw document and legal-unit IDs
    into canonical IDs used within the system.
    """
    def __init__(self, document_registry=None, unit_registry=None):
        self.document_registry = document_registry
        self.unit_registry = unit_registry

    def resolve_document(self, document_id: str) -> str:
        """
        Convert a raw document ID into its canonical form.
        Matches the behavior of the deprecated `normalize_so_hieu`.
        """
        if not document_id: 
            raise ValueError("so_hieu không được để trống")
        
        text = document_id.strip()
        text = text.replace("NĐ-CP", "ND-CP")
        text = text.replace("NĐCP", "ND-CP")
        text = text.replace("/", "_")
        
        text = unicodedata.normalize("NFD", text)
        text = "".join(
            c for c in text
            if unicodedata.category(c) != "Mn"
        )

        text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
        text = re.sub(r"_+", "_", text)

        return text.strip("_")

    def resolve_unit(self, unit_id: str) -> str:
        """
        Convert a raw unit ID into its canonical form.
        Currently an identity mapping based on runtime behavior.
        """
        if not unit_id:
            return unit_id
        return unit_id.strip()
