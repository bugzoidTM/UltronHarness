# Checkpoint — Project Athena

## Evidência obtida

O CGFE-10 foi executado com `qwen2.5:3b`, UGIB-Lite 0.2 e seeds 42–51. O resultado agregado foi fresh médio 0,712, experienced médio 0,720 e mean(CGFE) +0,008. O gate operacional Athena-1 (`mean(CGFE) > 0`) passou, mas o intervalo de confiança de 95% do CGFE ainda inclui zero; o efeito não deve ser descrito como forte.

## Implementação concluída nesta sessão

O banco SQLite recebeu `memory_write_decisions` e `capability_estimates`. Foram implementados `ultron/memory/governor.py`, com MAS explicável e bloqueio de writeback privado/duplicado/sem evidência, `ultron/cognition/self_model.py`, com posterior Beta empírica, e `ultron/learning/skill_governor.py`, com health score e estados recomendados. O `ExperienceCycle` passou a depender do governor, em vez de transformar qualquer sucesso em skill.

A auditoria de reuso foi salva em `data/artifacts/research/ports/athena_governors_port.md`; nenhum código do UltronLocal foi copiado porque o repositório continua sem licença declarada. As ideias foram reimplementadas contra SQLite e sob shadow/experimental.

## Próxima etapa obrigatória

Completar `benchmarks/transfer20/` para 20 tarefas em múltiplas famílias, adicionar o harness que mede Fresh versus Experienced sem vazar objetivos, fixtures ou respostas privadas ao corpus, persistir `transfer_runs` em SQLite e executar três ou mais seeds. Somente `mean(TG) > 0` em famílias relacionadas não vistas permite declarar Athena-3/Transfer Gain positivo.

## Transfer-20 em construção

Foram criadas as 20 tarefas públicas divididas em quatro famílias relacionadas — validação estruturada, recuperação de dependência, recuperação Git e planejamento de workflow — com contratos privados separados. A próxima implementação é o runner de transferência, que deverá carregar YAML corretamente, executar fresh e experienced com corpus originado apenas do domínio A e registrar `transfer_runs` antes de qualquer alegação de Transfer Gain.

A tabela canônica `transfer_runs` foi adicionada ao schema SQLite para que cada comparação fresh/experienced registre Transfer Gain, família, modelo, seed e diretório de artefatos.

A inicialização do schema expandido e a suíte estrutural continuaram aprovadas: 16 testes de pesquisa passaram após a inclusão de `transfer_runs`.

Próximo passo imediato: implementar o runner de `Transfer-20`, validar isolamento entre corpus de origem e respostas privadas e executar ao menos três seeds antes de declarar qualquer Transfer Gain.

O runtime de pesquisa permanece disponível localmente: `qwen2.5:3b` via Ollama, sem dependência de modelos em nuvem.

O trabalho não considera Transfer Gain confirmado nesta etapa; a estrutura e as proteções contra vazamento estão em preparação, e somente runs completos poderão alterar essa conclusão.

O primeiro teste do Transfer-20 confirmou 20 tarefas públicas, 20 contratos privados e bloqueio determinístico quando texto de tarefa tentaria entrar no corpus de experiência.

Lint aprovado para os módulos de Transfer-20, Memory Governor, Self Model e Skill Governor.

A inspeção do checkpoint confirma que o próximo requisito científico pendente permanece a execução do runner Transfer-20 em múltiplas seeds.

Transfer-20 foi executado em seeds 42–44. A seleção por família obteve TGs -0,10, -0,15 e -0,10; mean(TG) = -0,1167. O gate Athena-3 falhou e a seleção de contexto para transferência permanece em shadow/rejected, sem promoção.

Após os runs de transferência rejeitados, os testes de pesquisa continuaram aprovados (17 passed) e o lint dos módulos Athena passou sem erros.

Quatro diretórios de artefatos Transfer-20 foram preservados, incluindo a condição genérica inicial e três seeds da condição selecionada por família.

Hipótese seguinte para Transfer-20: substituir perguntas factuais de baixo espaço de ganho por pares processuais verificáveis, preservando os artefatos negativos anteriores e sem introduzir fatos do domínio-alvo no corpus de origem.

A inspeção do dataset confirmou que o conjunto inicial tem perguntas factuais em vez de tarefas processuais; ele será mantido como resultado negativo e não usado para promoção.

O contrato privado do Transfer-20 foi validado sintaticamente e permanece separado das tarefas públicas.

Checkpoint persistido com sucesso após a análise do Transfer-20 inicial.

O modelo `qwen2.5:3b` permanece ativo localmente em CPU e disponível para a próxima rodada experimental.

A validação estrutural continua aprovada com 17 testes de pesquisa após a execução e a rejeição da primeira configuração Transfer-20.

Foi criado o blueprint do Transfer-20 processual, com pares por família, fixtures e verificadores determinísticos como requisito antes de nova medição de TG.

O blueprint processual do Transfer-20 foi persistido no repositório local para implementação em uma rodada posterior.

Checkpoint operacional confirmado após a rodada inicial de Transfer-20 e o planejamento do redesign processual.

## Fase K — Transfer-20 processual (redesign v2)

O Transfer-20 factual original foi preservado como controle negativo. A versão `procedural-v2` usa 20 casos públicos com ações declaradas e contratos privados `expected_sequence`, avaliados por comparação determinística da sequência de ações. O corpus de origem contém apenas procedimentos abstratos; o guard de isolamento rejeita texto de tarefas públicas e contratos privados.

Em três seeds controladas do `ollama_research` (42, 43 e 44), a condição fresh obteve média de 0,200 e a condição experienced média de 0,466667. O **Transfer Gain médio foi +0,266667**, com IC95% aproximado de [+0,234000, +0,299333]. O gate Athena-3 passa para esta versão processual, com evidência positiva inicial e rastros por tarefa preservados em `data/artifacts/transfer/` e síntese em `data/artifacts/research/transfer20_procedural_multiseed.json`.

O resultado é heterogêneo e não autoriza promoção global: `dependency_recovery` teve ganho médio +0,933333 e `structured_validation` +0,333333, enquanto `recovery` ficou em 0,000000 e `planning` em -0,200000. Portanto, apenas as famílias com ganho positivo seguem elegíveis para shadow mode; as famílias neutra e negativa permanecem explicitamente não promovidas.

## Fase E — Symbolic Lane (shadow)

Foi criado o pacote `ultron/cognition/symbolic/` com avaliador matemático protegido por whitelist de AST, fatos com proveniência, motor de regras declarativo, classificadores conservadores e roteador em shadow mode. O roteador não altera a resposta do orquestrador: ele apenas registra candidatos de offload, **Symbolic Offload Rate** e **LLM Calls Saved Candidate**. A qualificação determinística do contrato declarado atingiu 100% em oito casos aritméticos e a suíte conjunta de Symbolic Lane e benchmarks passou com 22 testes. Não há promoção ao caminho padrão até haver validação no tráfego shadow representativo.

## Fases F e G — World Model e Evidence Critic (shadow)

Foi implementado `ultron/cognition/world_model.py`, que prevê o sucesso de ações por frequência com smoothing, registra resultado observado e calcula **Prediction Accuracy** e **Brier Score**. O componente não bloqueia ação, não altera plano e persiste as observações apenas como telemetria em `world_model_observations`. Foi implementado também `ultron/cognition/critic.py`: saída de testes, código de saída, existência de arquivo e validação de schema têm precedência sobre qualquer avaliação linguística; somente ausência de verificador determinístico torna o uso de crítico por modelo uma hipótese opcional. Sete testes das capacidades shadow passaram, incluindo persistência e prioridade de evidência.

## Fases H e I — Deliberação contrafactual e política de estratégia (shadow)

Foram incluídos `ultron/cognition/counterfactual.py` e `ultron/cognition/strategy_policy.py`. O deliberador exige evidência mínima e compara apenas alternativas com utilidade, risco e custo explicitamente observados; a política seleciona apenas estratégias com histórico mínimo e domínio compatível. Ambos devolvem recomendações shadow, sem acionar ferramentas, sem editar código e sem mudar o plano de produção. Os testes específicos passaram em conjunto com os demais módulos shadow (9 testes).

## Fase J — LEARN-2 (curva de experiências filtradas)

O LEARN-2 foi executado com `ollama_research`, seed 42, uma baseline fresh pareada e pontos N = 0, 10, 25, 50, 100 e 200. O pool continha 200 procedimentos curados, verificados pelo MAS e distribuídos por categoria. O score fresh foi 0,680 em todos os pontos; o score experienced foi 0,680 em N=0, 10, 50, 100 e 200, e 0,660 em N=25. Portanto, a curva observada é **neutra com uma regressão pontual de -0,0200**, sem evidência de efeito positivo de quantidade nesta configuração. O gate CG-2 não é promovido: qualidade de admissão, por si só, não demonstrou escala de capacidade; o resultado foi preservado em `diagnostic_runs` e no artefato LEARN-2 local.

## Dashboard Research v3

A API e a interface React agora mostram painéis de Learning (LEARN-2), Self Model, Memory & Skills, World Model e Transfer, alimentados por dados locais de SQLite e artefatos de pesquisa. O build React passou e o teste do contrato da API confirmou os novos agregados. Os painéis exibem dados observados, incluindo resultados neutros ou negativos, e não promovem automaticamente qualquer módulo shadow.

## Quality gates finais

A suíte determinística passou com **36 testes** e cobertura total de **73,15%** (limite ≥70%). A segurança Windows passou com **12 testes e 1 skipped**; os testes de agente passaram com **9 testes e 1 xfailed**. O lint `ruff` passou sem achados; o build React passou; e `scripts/smoke.ps1` confirmou API, política, aprovação supervisionada, memória persistente e UI local disponíveis. Esses gates verificam funcionamento do produto, não equivalem à promoção automática de módulos Athena ainda em shadow.

O relatório científico consolidado foi salvo em `ATHENA_DIAGNOSTIC_REPORT.md`, com a resposta delimitada à pergunta central, os resultados positivos e negativos, os artefatos de auditoria e as decisões de promoção.
