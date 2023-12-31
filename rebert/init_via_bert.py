import torch
from torch.nn import ModuleList
from transformers.models.roberta.modeling_roberta import RobertaEmbeddings, RobertaModel, RobertaLMHead, \
    RobertaAttention

from .model import ReBertEmbedding, ReBertModel, ReBertLMHead, ReBertConfig, ReBertMultiHeadAttention


def load_transformers_embeddings(tf_embedding: RobertaEmbeddings, embeddings: ReBertEmbedding):
    with torch.no_grad():
        embeddings.word_embedding.weight.copy_(
            tf_embedding.word_embeddings.weight + tf_embedding.token_type_embeddings.weight[0])
        embeddings.layer_norm.weight.copy_(tf_embedding.LayerNorm.weight)
        embeddings.layer_norm.bias.copy_(tf_embedding.LayerNorm.bias)


def average_attention_head_weights(src_weight: torch.Tensor, size_per_head, num_heads, kv_head_group_size):
    if kv_head_group_size == 1:
        return src_weight

    input_size = size_per_head * num_heads
    kv_group = num_heads // kv_head_group_size
    src_weight = src_weight.reshape(num_heads, size_per_head, input_size)
    output_weight = torch.zeros((kv_group, size_per_head, input_size))

    for i in range(kv_group):
        start = i * kv_head_group_size
        end = start + kv_head_group_size
        head_buffer = src_weight[start:end, :, :]
        output_weight[i, :, :] = torch.mean(head_buffer, dim=0, keepdim=False)

    return output_weight.reshape(-1, input_size)


def average_attention_head_biases(src_weight: torch.Tensor, size_per_head, num_heads, kv_head_group_size):
    if kv_head_group_size == 1:
        return src_weight

    kv_group = num_heads // kv_head_group_size
    src_weight = src_weight.reshape(num_heads, size_per_head)
    output_weight = torch.zeros(kv_group, size_per_head)

    for i in range(kv_group):
        start = i * kv_head_group_size
        end = start + kv_head_group_size
        head_buffer = src_weight[start:end, :]
        output_weight[i, :] = torch.mean(head_buffer, dim=0, keepdim=False)

    return output_weight.reshape(kv_group * size_per_head)


def load_grouped_attention(tf_attention: RobertaAttention, rebert_attention: ReBertMultiHeadAttention,
                           config: ReBertConfig):
    size_per_head = config.hidden_size // config.num_attention_heads
    kv_head_group_size = config.num_attention_heads // config.num_key_value_heads

    # Linear Weights
    self = rebert_attention.self_attention
    src_self = tf_attention.self
    self.k_proj.weight.copy_(
        average_attention_head_weights(src_self.key.weight, size_per_head, config.num_attention_heads,
                                       kv_head_group_size))
    self.q_proj.weight.copy_(src_self.query.weight)
    self.v_proj.weight.copy_(
        average_attention_head_weights(src_self.value.weight, size_per_head, config.num_attention_heads,
                                       kv_head_group_size))
    rebert_attention.o_proj.weight.copy_(tf_attention.output.dense.weight)

    # Linear Bias
    self.k_proj.bias.copy_(
        average_attention_head_biases(src_self.key.bias, size_per_head, config.num_attention_heads, kv_head_group_size))
    self.q_proj.bias.copy_(src_self.query.bias)
    self.v_proj.bias.copy_(average_attention_head_biases(src_self.value.bias, size_per_head, config.num_attention_heads,
                                                         kv_head_group_size))
    rebert_attention.o_proj.bias.copy_(tf_attention.output.dense.bias)


def load_transformers_encoders(tf_layers: ModuleList, layers: ModuleList, config: ReBertConfig):
    with torch.no_grad():
        for tf_l, l in zip(tf_layers, layers):
            # Attention
            load_grouped_attention(tf_l.attention, l.attention, config)

            # Intermediate Linear
            l.intermediate_proj.weight.copy_(tf_l.intermediate.dense.weight)
            l.intermediate_proj.bias.copy_(tf_l.intermediate.dense.bias)

            # Output Linear
            l.out_proj.weight.copy_(tf_l.output.dense.weight)
            l.out_proj.bias.copy_(tf_l.output.dense.bias)


def load_transformers_base_bert(tf_bert: RobertaModel, bert_base: ReBertModel, config: ReBertConfig):
    load_transformers_embeddings(tf_bert.embeddings, bert_base.embedding)
    load_transformers_encoders(tf_bert.encoder.layer, bert_base.encoder.encoder_layers, config)


def load_transformers_base_mlm(tf_mlm: RobertaLMHead, mlm: ReBertLMHead):
    with torch.no_grad():
        mlm.transform.weight.copy_(tf_mlm.dense.weight)
        mlm.transform.bias.copy_(tf_mlm.dense.bias)
        mlm.decoder.weight.copy_(tf_mlm.decoder.weight)


def migrate_grouped_attention(src: ReBertMultiHeadAttention, target: ReBertMultiHeadAttention,
                              config: ReBertConfig, src_kv_heads: int):
    target.o_proj.load_state_dict(src.o_proj.state_dict())
    target.prelayer_norm.load_state_dict(src.prelayer_norm.state_dict())
    target.self_attention.q_proj.load_state_dict(src.self_attention.q_proj.state_dict())

    size_per_head = config.hidden_size // config.num_attention_heads
    assert src_kv_heads % config.num_key_value_heads == 0
    kv_head_group_size = src_kv_heads // config.num_key_value_heads

    # Key
    target.self_attention.k_proj.weight.copy_(
        average_attention_head_weights(src.self_attention.k_proj.weight, size_per_head, src_kv_heads,
                                       kv_head_group_size))
    target.self_attention.k_proj.bias.copy_(
        average_attention_head_biases(src.self_attention.k_proj.bias, size_per_head, src_kv_heads, kv_head_group_size))

    # Value
    target.self_attention.v_proj.weight.copy_(
        average_attention_head_weights(src.self_attention.v_proj.weight, size_per_head, src_kv_heads,
                                       kv_head_group_size))
    target.self_attention.v_proj.bias.copy_(
        average_attention_head_biases(src.self_attention.v_proj.bias, size_per_head, src_kv_heads, kv_head_group_size))


def migrate_rebert(src: ReBertModel, target: ReBertModel, config: ReBertConfig, src_kv_heads: int):
    with torch.no_grad():
        target.embedding.load_state_dict(src.embedding.state_dict())
        for src_l, target_l in zip(src.encoder.encoder_layers, target.encoder.encoder_layers):
            # Attention
            migrate_grouped_attention(src_l.attention, target_l.attention, config, src_kv_heads)

            # Intermediate Linear
            target_l.layer_norm.load_state_dict(src_l.layer_norm.state_dict())
            target_l.intermediate_proj.load_state_dict(src_l.intermediate_proj.state_dict())

            # Output Linear
            target_l.out_proj.load_state_dict(src_l.out_proj.state_dict())
        target.layer_norm.load_state_dict(src.layer_norm.state_dict())
        try:
            src_pooler = getattr(src, "pooler")
            target_pooler = getattr(target, "pooler")
            target_pooler.load_state_dict(src_pooler.state_dict())
        except AttributeError:
            pass
