# Emenda de validação pós-freeze do General Reasoning v1

## Motivo

A primeira coleta de validation pós-freeze foi encerrada parcialmente e não pode ser usada como evidência. A auditoria sanitizada identificou um erro de integração no pós-processador pareado: o trace emitia o identificador `private_mission_evaluator` para o OutcomeAuthority, enquanto o auditor esperava outro identificador. Como consequência, os pares concluídos foram marcados com `pair:outcome_authority_mismatch` apesar de o artefato Horizon indicar medição operacional válida.

## Tratamento

A coleta parcial `collection_20260825T163733Z` foi preservada como artefato histórico inválido e não será analisada como resultado científico. O ajuste limita-se ao mapeamento do identificador emitido pelo trace para o gate sanitizado de OutcomeAuthority. Nenhum contrato, resposta, regra gold, família, split, seed, modelo ou critério estatístico foi alterado.

A validação pós-emenda será executada com novo hash de código e novo `freeze_manifest_hash`, mantendo o mesmo benchmark privado rotacionado, o modelo efetivo `qwen2.5:0.5b`, a seed 53, o modo `full_plan`, a ordem determinística randomizada por seed, o evaluator privado externo e o labeler independente privado. O unseen permanece fechado até a validação pós-emenda completar todos os gates.

## Estado

A emenda foi testada com a suíte direcionada e Ruff. A nova coleta será retomável a partir de seu próprio checkpoint. Não haverá combinação entre a coleta invalidada e a coleta pós-emenda.
