# Protocolo de execução recuperável — Transfer-100

A rodada inicial multi-seed com chunks de cinco tarefas foi interrompida após exceder uma hora sem checkpoint consolidado. Os artefatos por seed já concluídos foram preservados e não serão misturados à próxima configuração sem identificação de protocolo.

A validação de seed 46 do protocolo JSON, com uma chamada por família e condições fresh/experienced idênticas em estrutura, terminou com fresh 0,200, experienced 0,300 e TG +0,100. Ela confirma que o parser estruturado funciona, mas também mostrou duração elevada no runtime local.

A continuação deverá registrar cada seed imediatamente após sua conclusão, limitar a geração à resposta JSON necessária e permitir retomada por seeds ausentes. Nenhuma conclusão Hermes-1 será emitida antes de dez seeds comparáveis da mesma versão de protocolo.
