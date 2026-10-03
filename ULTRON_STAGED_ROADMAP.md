# Ultron — Roadmap em etapas com gates

Este documento ordena o trabalho em oito etapas. Cada etapa só começa quando a anterior fecha o seu gate. Cada mecanismo precisa demonstrar ganho contra a versão imediatamente anterior, com o **mesmo modelo-base** e o **mesmo orçamento computacional**. "Mesmo orçamento" inclui um controle de compute pareado: a condição de controle recebe as mesmas chamadas e tokens sem o mecanismo. O Genesis mostrou que, sem esse controle, chamadas extras se confundem com ganho cognitivo.

Os detalhes de GR-2 a GR-9 continuam em [`GENERAL_REASONING_ROADMAP.md`](GENERAL_REASONING_ROADMAP.md) e [`GR2_GENERALIZATION_PROTOCOL.md`](GR2_GENERALIZATION_PROTOCOL.md). Aqui ficam a ordem, os gates e as decisões que cabem ao responsável humano.

## Regras transversais

| Regra | Conteúdo |
|---|---|
| Pré-registro | Protocolo, métricas, gate e leitura dos resultados são commitados antes da primeira execução live. O commit é a prova temporal. |
| Um mecanismo por vez | Cada etapa liga uma única flag nova. As anteriores ficam no estado já validado. |
| Controle de compute | Toda comparação inclui uma condição com o mesmo número de chamadas e tokens sem o mecanismo. |
| Observabilidade | Toda linha serializa a resposta candidata e separa falha cognitiva de falha de infraestrutura (lição da etapa 1). |
| Validade de interface | Antes de medir um mecanismo cognitivo, o modelo-base precisa passar um gate de interface num conjunto de calibração fora do benchmark: campos de conteúdo obrigatórios no schema, taxa de conformidade de schema, taxa de conteúdo vazio e acerto da resposta direta com o mesmo formato. Sem isso, um defeito de interface se confunde com falha de arquitetura ou de escala (lição da etapa 1). |
| Unseen nunca é ambiente de tentativa | Calibração e desenvolvimento usam splits públicos ou de validação. O split confirmatório é aberto uma única vez. |
| Segurança fixa | Nenhuma etapa altera Policy Engine, OutcomeAuthority, permissões, evaluator ou VerifiedWritebackGate sem revisão humana explícita. |

## Etapa 1 — Fechar o Genesis v2

| Item | Conteúdo |
|---|---|
| Objetivo | Separar "a arquitetura executiva falha" de "o modelo-base é pequeno demais". |
| Feito | Correção somente de observabilidade (`candidate_answer` sempre preservado; B e C igualmente observáveis), protocolo recongelado como v2-FINAL-OBS e escada 3B → 7B → 14B pré-registrada no mesmo hardware. Ver [`GENESIS_V0_1_PROTOCOL.md`](GENESIS_V0_1_PROTOCOL.md). |
| Gate de saída | Genesis v2 encerrado com veredito registrado. Nenhum v2.x. |
| Status | **Fechada: `NOT_SUPPORTED`.** `PARTIAL_VALIDITY` em 3B/7B/14B; o controlador fixo fica válido com escala (2/2 no 14B) e o endógeno não (≤ 1/2 em todas as escalas, por repetir o mesmo operador sem progresso). `ECG-task ≤ 0` e `ECG-self = −0,5` em todas as escalas. |
| Lições levadas adiante | (1) Um controlador que deixa o modelo escolher o próximo passo precisa de proteção contra ausência de progresso. (2) A interface estruturada precisa passar um gate de validade antes de qualquer comparação cognitiva (ver regra transversal). (3) Resultados de seed única não se reproduzem entre runtimes: o 3B teve `V = 0/4` no Windows e `1/4` aqui. |

## Etapa 2 — Concluir GR-2 cientificamente

| Item | Conteúdo |
|---|---|
| Objetivo | Medir se Prediction Before Observation (GR-2) melhora a conclusão externa autoritativa sobre GR-1 em famílias genuinamente unseen. |
| Entrada | Etapa 1 fechada. Modelo-base confirmatório decidido e congelado (o manifesto atual exige `qwen2.5:0.5b`; a etapa 1 pode justificar trocá-lo antes do freeze, nunca depois). |
| Isolamento do benchmark | Contratos, gerador de instâncias, evaluator e manifesto de splits ficam fora do repositório público (`research.private_benchmark_root`). O repositório público recebe só o SHA-256 do manifesto privado, commitado antes da coleta. Instâncias são geradas a partir de seeds secretas, para que cada execução use instâncias novas. Strings canário em cada contrato permitem detectar vazamento para prompts, memória, logs ou repositório. |
| Autoria isolada | As famílias unseen devem ser escritas por um processo que não participa da engenharia do harness (outra pessoa, ou uma sessão de agente separada sem acesso de escrita ao harness e sem retorno de resultados para esta linha de trabalho). |
| Evaluator externo | Processo separado que lê somente o estado final real e o contrato privado. Ele nunca é importado pelo runtime do agente. |
| Auditoria de leakage | Antes da análise: varredura de canários e de n-gramas dos contratos privados contra prompts, eventos, memória, artefatos e histórico git (`scripts/scan_private_contracts.py` como base). Qualquer achado invalida a coleta. |
| Desenho | GR-1 × GR-2 pareado por missão e seed; 10 famílias primárias + 2 reservas; 4 seeds; bootstrap agrupado por família; McNemar como sensibilidade; efeito mínimo de interesse de 5 p.p. |
| Gate | Promover GR-2 somente se IC95 excluir zero, o efeito superar 5 p.p., não se concentrar em uma família e não for explicado por custo. Caso contrário GR-2 não é promovido e permanece desligado. |

## Etapa 3 — GR-3 a GR-6, um de cada vez

Ordem fixa: hipóteses concorrentes (GR-3) → falsificação de premissas (GR-4) → estado causal (GR-5) → checagem contrafactual (GR-6). Cada GR-k é comparado com GR-(k−1) no mesmo benchmark da etapa 2 (novas instâncias, mesmas famílias unseen congeladas), com o mesmo modelo, a mesma seed e um controle de compute pareado. Um GR-k que não passa o gate não é empilhado: o próximo é comparado com a última versão aprovada.

## Etapa 4 — Meta-controller cognitivo (Horizon + Genesis)

| Item | Conteúdo |
|---|---|
| Objetivo | Aprender quando usar REPRESENT, HYPOTHESIZE, VERIFY, memória, ferramentas ou raciocínio causal, em vez de seguir uma sequência escrita à mão. |
| Base | Estado epistêmico, previsão e controle de tarefas do Horizon; operadores e trace do Genesis. |
| Lição do Genesis | Pedir ao próprio LLM o próximo operador (`next_operator`) depende da capacidade do modelo de seguir schemas e não aprende com resultados. O meta-controller deve aprender a política a partir de traces com outcome externo (por exemplo, um contextual bandit sobre features do estado epistêmico), treinada em famílias de treino e avaliada em famílias unseen. |
| Controles | (a) sequência fixa do Horizon; (b) controlador fixo do Genesis (B); (c) seleção aleatória com a mesma distribuição de custo. Mesmo orçamento em todos. |
| Gate | Ganho sobre o melhor controle fixo em famílias unseen, com IC95 e sem ganho explicado por mais chamadas. |

## Etapa 5 — LIFE com transferência real

| Item | Conteúdo |
|---|---|
| Objetivo | Provar transferência: aprender na família A e melhorar na família B sem receber a solução de B. |
| Desenho | Treino somente em A. Avaliação em B com: baseline fresco; memória de A literal; princípio abstraído de A. Pares A→B escolhidos antes da coleta, incluindo pares em que a transferência não deveria ajudar (controle de transferência negativa). |
| Gate | Ganho em B sobre o baseline fresco, sem nenhum conteúdo de B na memória (verificado pela auditoria de leakage) e sem degradação em pares de controle. Armazenar memória sem esse ganho não conta. |

## Etapa 6 — World model aprendido

| Item | Conteúdo |
|---|---|
| Objetivo | Construir modelos internos de ambientes novos: variáveis, relações causais, efeitos de ações, incerteza e mudanças de estado. |
| Ambientes | Gerados proceduralmente com dinâmica oculta (máquinas de estado, sistemas com variáveis acopladas), com seeds secretas. |
| Teste | Antes de cada ação, o agente registra uma previsão falsificável do próximo estado com confiança. Métricas: acurácia de previsão em ações não vistas, Brier/calibração, eficiência de exploração e sucesso de planejamento via modelo. |
| Gate | Previsões melhores que um baseline sem modelo explícito e calibração dentro do limite pré-registrado, em ambientes unseen. |

## Etapa 7 — Autoaperfeiçoamento controlado

| Item | Conteúdo |
|---|---|
| Ciclo | Detectar limitação → formular hipótese de melhoria → gerar alteração em branch isolada → testes e benchmarks → comparar baseline × candidato → promoção somente com evidência e aprovação humana. |
| Superfície permitida | Prompts, políticas cognitivas, configurações de operadores e código de cognição listado explicitamente. |
| Superfície proibida | Segurança, permissões, Policy Engine, OutcomeAuthority, evaluator, benchmarks, CI e os próprios gates. Um guard de caminhos no CI rejeita qualquer diff que toque nessa lista. |
| Avaliação | Somente no split de validação. O split confirmatório nunca é visível ao ciclo de melhoria (evita Goodhart sobre o benchmark). |
| Promoção | Pull request com evidência anexada. Nunca merge automático. |

## Etapa 8 — Gate de generalidade ("AGI gate")

Só abre depois das etapas 1–7. Exige, em domínios unseen e tarefas criadas depois do congelamento: generalização entre muitos domínios, aprendizagem a partir de pouca experiência, planejamento de longo horizonte, criação de subobjetivos, transferência entre domínios, recuperação após falhas, calibração de incerteza e desempenho sustentado ao longo do tempo. Comparações obrigatórias: o mesmo modelo-base sem o Ultron e o mesmo modelo-base com um scaffold simples (cadeia de raciocínio/ReAct) com compute pareado. Sem esse segundo controle, o ganho de qualquer scaffold seria atribuído ao Ultron. O resultado é reportado como perfil de capacidades com intervalos de confiança, não como um rótulo binário de AGI.
