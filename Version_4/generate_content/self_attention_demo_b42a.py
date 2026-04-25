import torch
import torch.nn as nn
import torch.nn.functional as F

class SelfAttention(nn.Module):
    """Scaled dot‑product self‑attention.
    Input shape: (batch, seq_len, embed_dim)
    Returns: (batch, seq_len, embed_dim)
    """
    def __init__(self, embed_dim, num_heads=8, dropout=0.1):
        super().__init__()
        assert embed_dim % num_heads == 0, "embed_dim must be divisible by num_heads"
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.scale = self.head_dim ** -0.5

        self.qkv_proj = nn.Linear(embed_dim, embed_dim * 3, bias=False)
        self.out_proj = nn.Linear(embed_dim, embed_dim)
        self.attn_dropout = nn.Dropout(dropout)
        self.proj_dropout = nn.Dropout(dropout)

    def forward(self, x, mask=None):
        # x: (B, T, E)
        B, T, E = x.size()
        # Linear projection and split into Q, K, V
        qkv = self.qkv_proj(x)  # (B, T, 3*E)
        qkv = qkv.reshape(B, T, 3, self.num_heads, self.head_dim)
        q, k, v = qkv.unbind(dim=2)  # each: (B, T, heads, head_dim)
        # Transpose for attention computation
        q = q.transpose(1, 2)  # (B, heads, T, head_dim)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)
        # Scaled dot‑product
        attn_weights = (q @ k.transpose(-2, -1)) * self.scale  # (B, heads, T, T)
        if mask is not None:
            attn_weights = attn_weights.masked_fill(mask == 0, float('-inf'))
        attn_probs = F.softmax(attn_weights, dim=-1)
        attn_probs = self.attn_dropout(attn_probs)
        # Weighted sum
        context = attn_probs @ v  # (B, heads, T, head_dim)
        # Concatenate heads
        context = context.transpose(1, 2).contiguous().view(B, T, E)
        out = self.out_proj(context)
        return self.proj_dropout(out), attn_probs

class TransformerBlock(nn.Module):
    def __init__(self, embed_dim, num_heads, mlp_ratio=4.0, dropout=0.1):
        super().__init__()
        self.norm1 = nn.LayerNorm(embed_dim)
        self.attn = SelfAttention(embed_dim, num_heads, dropout)
        self.norm2 = nn.LayerNorm(embed_dim)
        self.mlp = nn.Sequential(
            nn.Linear(embed_dim, int(embed_dim * mlp_ratio)),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(int(embed_dim * mlp_ratio), embed_dim),
            nn.Dropout(dropout),
        )

    def forward(self, x, mask=None):
        # Self‑attention block
        attn_out, attn_weights = self.attn(self.norm1(x), mask)
        x = x + attn_out
        # Feed‑forward block
        mlp_out = self.mlp(self.norm2(x))
        x = x + mlp_out
        return x, attn_weights

if __name__ == "__main__":
    torch.manual_seed(0)
    batch_size, seq_len, embed_dim = 2, 10, 64
    x = torch.randn(batch_size, seq_len, embed_dim)
    # Optional causal mask (prevent attending to future tokens)
    causal_mask = torch.tril(torch.ones(seq_len, seq_len)).unsqueeze(0).unsqueeze(0)
    block = TransformerBlock(embed_dim=embed_dim, num_heads=8)
    out, attn = block(x, mask=causal_mask)
    print("Output shape:", out.shape)
    print("Attention shape:", attn.shape)  # (B, heads, T, T)
    # Show attention for first head of first sample
    print("Attention weights (sample 0, head 0):")
    print(attn[0, 0])
