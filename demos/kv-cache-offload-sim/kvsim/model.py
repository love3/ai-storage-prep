"""Model geometry -> KV cache size math (see KB 10/11)."""

from dataclasses import dataclass


@dataclass
class ModelConfig:
    """Transformer geometry needed to size the KV cache.

    KV bytes/token = 2 (K and V) * n_layers * n_kv_heads * head_dim * bytes_per_elem
    GQA/MQA reduce n_kv_heads; KV quantization reduces bytes_per_elem.
    """

    name: str = "llama-3-8b-ish"
    n_layers: int = 32
    n_kv_heads: int = 8        # GQA: 8 KV heads (vs 32 query heads)
    head_dim: int = 128
    bytes_per_elem: float = 2.0  # FP16=2, FP8/INT8=1, INT4=0.5
    block_tokens: int = 16       # PagedAttention block size

    def with_kv_dtype_bytes(self, b: float) -> "ModelConfig":
        return ModelConfig(self.name, self.n_layers, self.n_kv_heads,
                           self.head_dim, b, self.block_tokens)


def kv_bytes_per_token(m: ModelConfig) -> float:
    return 2 * m.n_layers * m.n_kv_heads * m.head_dim * m.bytes_per_elem


def kv_bytes_per_block(m: ModelConfig) -> float:
    return kv_bytes_per_token(m) * m.block_tokens


PRESETS = {
    "llama-3-8b": ModelConfig("llama-3-8b", n_layers=32, n_kv_heads=8, head_dim=128),
    "llama-2-13b-mha": ModelConfig("llama-2-13b-mha", n_layers=40, n_kv_heads=40, head_dim=128),
    "llama-3-70b": ModelConfig("llama-3-70b", n_layers=80, n_kv_heads=8, head_dim=128),
    "mistral-7b": ModelConfig("mistral-7b", n_layers=32, n_kv_heads=8, head_dim=128),
}
