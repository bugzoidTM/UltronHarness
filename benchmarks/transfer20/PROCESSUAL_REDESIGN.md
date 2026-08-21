# Redesign processual do Transfer-20

O conjunto inicial permanece como controle negativo. A versão processual deverá substituir perguntas de conhecimento isolado por pares de tarefas que exigem a mesma estratégia observável em domínios distintos. Cada par terá fixture, ação permitida, artefato verificável e avaliador determinístico.

| Família de origem | Família-alvo relacionada | Estratégia transferível permitida | Evidência-alvo |
|---|---|---|---|
| Diagnóstico de dependência Python | Diagnóstico de dependência Node.js | inspecionar manifesto, reconhecer recurso ausente, restaurar dependência e verificar | arquivo/lockfile e saída de verificação |
| Validação JSON | Validação YAML | validar estrutura, tipo obrigatório e erro de parse antes de aceitar | schema e resultado do parser |
| Recuperação de arquivo | Recuperação Git | inspecionar estado, preservar escopo e aplicar reversão permitida | `git status` e artefato restaurado |
| Planejamento algorítmico | Planejamento de workflow | ordenar dependências e bloquear a etapa dependente até pré-condição | grafo validado e ordem topológica |

O corpus de origem só poderá conter procedimentos generalizáveis, por exemplo “validar pré-condições antes de uma recuperação”. Ele não poderá mencionar comandos, respostas, fixtures, nomes de arquivos ou gabaritos do domínio-alvo. O avaliador deve comparar a tarefa fresh contra a condição com procedimento selecionado, em pelo menos três seeds, e registrar Transfer Gain por família.
