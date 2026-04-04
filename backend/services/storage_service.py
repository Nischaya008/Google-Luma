"""
Artifact serialization and Supabase Storage management.

Handles gzip compression, upload, and download of:
- NetworkX graphs (.graphml → gzip)
- Pandas DataFrames (.parquet with built-in compression)
- ML models (pickle → gzip)
- Numpy arrays (.npz compressed)

All operations are fault-tolerant — failures return None/False
so callers can cascade to fresh computation.
"""
import gzip
import io
import os
import pickle
import tempfile
import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from core.config import settings
from db.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class StorageService:
    """
    Handles serialization, compression, and Supabase Storage I/O
    for all artifact types used in the caching system.
    """

    def __init__(self):
        self._supabase = SupabaseClient.get_instance()

    @property
    def is_available(self) -> bool:
        return self._supabase.is_available

    # ══════════════════════════════════════════════════════════════════════════
    # Graph Operations (NetworkX MultiDiGraph ↔ GraphML + gzip)
    # ══════════════════════════════════════════════════════════════════════════

    def upload_graph(self, G, storage_path: str) -> bool:
        """
        Serialize a NetworkX graph to GraphML, gzip compress, upload.
        A 52 MB GraphML typically compresses to ~5-8 MB.
        """
        import networkx as nx
        import osmnx as ox

        if not self.is_available:
            return False
        try:
            # OSMnx save_graphml requires a file path — use temp file
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".graphml")
            os.close(tmp_fd)
            try:
                ox.save_graphml(G, filepath=tmp_path)
                with open(tmp_path, "rb") as f:
                    raw_data = f.read()
            finally:
                os.unlink(tmp_path)

            compressed = gzip.compress(raw_data, compresslevel=6)
            logger.info(
                f"Graph compressed: {len(raw_data):,} → {len(compressed):,} bytes "
                f"({100 * len(compressed) / len(raw_data):.0f}%)"
            )
            return self._supabase.upload_file(storage_path, compressed)
        except Exception as e:
            logger.error(f"Graph upload failed: {e}")
            return False

    def download_graph(self, storage_path: str):
        """Download, decompress, and load a graph from Supabase Storage."""
        import osmnx as ox

        if not self.is_available:
            return None
        try:
            compressed = self._supabase.download_file(storage_path)
            if compressed is None:
                return None

            raw_data = gzip.decompress(compressed)

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".graphml")
            os.close(tmp_fd)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(raw_data)
                G = ox.load_graphml(filepath=tmp_path)
            finally:
                os.unlink(tmp_path)

            logger.info(
                f"Graph loaded from storage: {len(G.nodes)} nodes, {len(G.edges)} edges"
            )
            return G
        except Exception as e:
            logger.error(f"Graph download failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # Feature DataFrame Operations (Pandas ↔ Parquet)
    # ══════════════════════════════════════════════════════════════════════════

    def upload_features(self, df: pd.DataFrame, storage_path: str) -> bool:
        """Serialize DataFrame to parquet (with built-in compression) and upload."""
        if not self.is_available:
            return False
        try:
            buf = io.BytesIO()
            # Parquet has built-in compression — no need for extra gzip
            df.to_parquet(buf, engine="pyarrow", compression="gzip")
            data = buf.getvalue()
            logger.info(f"Features serialized: {len(df)} rows → {len(data):,} bytes")
            return self._supabase.upload_file(storage_path, data)
        except Exception as e:
            logger.error(f"Features upload failed: {e}")
            return False

    def download_features(self, storage_path: str) -> Optional[pd.DataFrame]:
        """Download and deserialize a feature DataFrame from storage."""
        if not self.is_available:
            return None
        try:
            data = self._supabase.download_file(storage_path)
            if data is None:
                return None
            df = pd.read_parquet(io.BytesIO(data), engine="pyarrow")
            logger.info(f"Features loaded from storage: {len(df)} rows")
            return df
        except Exception as e:
            logger.error(f"Features download failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # ML Model Operations (Pickle + gzip)
    # ══════════════════════════════════════════════════════════════════════════

    def upload_model(self, model: Any, storage_path: str) -> bool:
        """Pickle + gzip compress + upload an ML model."""
        if not self.is_available:
            return False
        try:
            pickled = pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)
            compressed = gzip.compress(pickled, compresslevel=6)
            logger.info(f"Model serialized: {len(compressed):,} bytes")
            return self._supabase.upload_file(storage_path, compressed)
        except Exception as e:
            logger.error(f"Model upload failed: {e}")
            return False

    def download_model(self, storage_path: str) -> Optional[Any]:
        """Download, decompress, and unpickle an ML model."""
        if not self.is_available:
            return None
        try:
            compressed = self._supabase.download_file(storage_path)
            if compressed is None:
                return None
            model = pickle.loads(gzip.decompress(compressed))
            logger.info(f"Model loaded from storage: {storage_path}")
            return model
        except Exception as e:
            logger.error(f"Model download failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # Numpy Array Operations (npz compressed)
    # ══════════════════════════════════════════════════════════════════════════

    def upload_numpy(self, arrays: dict, storage_path: str) -> bool:
        """Upload a dict of numpy arrays as a compressed .npz file."""
        if not self.is_available:
            return False
        try:
            buf = io.BytesIO()
            np.savez_compressed(buf, **arrays)
            data = buf.getvalue()
            logger.info(f"Numpy arrays serialized: {len(data):,} bytes")
            return self._supabase.upload_file(storage_path, data)
        except Exception as e:
            logger.error(f"Numpy upload failed: {e}")
            return False

    def download_numpy(self, storage_path: str) -> Optional[dict]:
        """Download and load numpy arrays from a .npz file."""
        if not self.is_available:
            return None
        try:
            data = self._supabase.download_file(storage_path)
            if data is None:
                return None
            npz = np.load(io.BytesIO(data), allow_pickle=False)
            result = {key: npz[key] for key in npz.files}
            logger.info(f"Numpy arrays loaded: {list(result.keys())}")
            return result
        except Exception as e:
            logger.error(f"Numpy download failed: {e}")
            return None
