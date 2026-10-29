# Memória contínua para agentes em Kioku

## Objetivo e escopo

Esta especificação traduz `spec_memoria_continua_agentes_v1_1.docx` para uma implementação no Kioku atual. Manabi, como serviço local já instalado pelo CLI, coleta evidência de sessões do Claude Code e a envia pelo WebSocket existente. O backend confirma apenas depois de gravar o evento bruto. Mihari, como worker cloud já existente, transforma eventos em memórias julgadas e mantém um Living Summary versionado. O MCP expõe contexto e busca. Nenhum worker de memória ou API HTTP de ingestão adicional é necessário.

O produto distingue três coisas: **evento bruto** (evidência imutável), **memória consolidada** (afirmação com lifecycle e validade) e **Living Summary** (projeção compacta, reconstruível, de cinco seções). O histórico de cada memória é útil para correções e auditoria; o histórico de arquivos e briefing não volta à interface.

## Estado atual e diferenças para a implementação

- `cli/src/lib/manabi-client.ts` conecta a `/api/remotes/connect`, autentica com `hello`, envia `inventory` e `heartbeat`, e reconecta. `cli/src/lib/manabi-service.ts` registra launchd, systemd user service ou Windows Scheduled Task. Manabi **não é um container local hoje**; manter este modo de execução evita uma migração operacional sem relação com a memória.
- `backend/routes/remotes.py` aceita somente `inventory` e `heartbeat` após o `hello`. Seu limite atual de mensagem é 256 KiB. `remote_machines` guarda presença e inventário, não eventos de sessão.
- `mihari/mihari.py` faz polling de repositórios, indexação de código/grafo e atualização de briefing em um processo agendado. O pipeline de memória entra como módulos do mesmo processo, com agenda e limites independentes dos jobs de repositório.
- A migração `supabase/migrations/20261024000000_remove_mem0.sql` removeu a antiga tabela Mem0. Esta implementação cria tabelas próprias e não reativa Mem0.
- `backend/mcp_server.py` já autentica por API key com `scope_folder_id`. `backend/services/search.py` oferece busca híbrida de documentos/código, mas a busca de memórias terá índice e filtros próprios para impedir que versões inválidas entrem no pool de candidatos.

## Invariantes de segurança e consistência

1. Um evento aceito recebe confirmação somente após commit durável. Reenvio do mesmo `event_id` e `content_hash` devolve a mesma confirmação; mesmo ID com hash diferente é conflito, nunca sobrescrita.
2. Evento bruto permanece imutável. Redação ou exclusão por privacidade cria uma tombstone auditável e remove o conteúdo recuperável conforme a política de retenção; não converte silenciosamente o evento em resumo.
3. Só memória `ACTIVE`, dentro de escopo e intervalo de validade, aparece na recuperação corrente. `MERGED`, `SUPERSEDED` e `DISCARDED` nunca são resultados correntes; candidatos `PENDING_REVIEW` ainda não são memórias publicadas.
4. A decisão que invalida uma memória e a mudança de seu estado ocorrem na mesma transação. A consulta valida o estado no banco **depois** de buscar IDs no índice; um vetor atrasado não pode reexpor texto antigo.
5. Toda memória e afirmação de summary apontam para evidências. Texto de logs, arquivos e ferramentas é dado não confiável e nunca instrui o Judge.
6. Captura, julgamento, indexação e summary são assíncronos. Falha cloud não atrasa nem bloqueia a sessão do agente.
7. O backend/MCP e Supabase existentes continuam como infraestrutura. “Manabi e Mihari” são os dois executores do fluxo de memória; a topologia já existente de backend, MCP e frontend não é removida.

## Fluxo de ponta a ponta

```mermaid
sequenceDiagram
    participant C as Claude Code JSONL
    participant M as Manabi local
    participant B as Backend WebSocket
    participant D as Supabase
    participant H as Mihari cloud
    participant P as MCP
    M->>C: Ler registros novos desde checkpoint
    M->>M: Validar origem, atribuir escopo e redigir segredos
    M->>B: memory_post(event_id, hash, payload)
    B->>D: Inserir evento bruto e item HOLDING em transação
    D-->>B: Commit
    B-->>M: memory_ack(event_id)
    M->>M: Avançar checkpoint durável
    H->>D: Claim de HOLDING com lease
    H->>D: Extrair candidatos e buscar ACTIVE relacionadas
    H->>H: Judge estruturado
    H->>D: Commit de lifecycle, evidências, relações e outbox
    H->>D: Indexar ACTIVE; marcar escopo dirty
    P->>D: Buscar ACTIVE e validar estado/escopo/validade
    H->>D: Publicar snapshot de cinco seções por janela
```

## 1. Captura e transporte em Manabi

### Fonte e checkpoint

Criar `cli/src/lib/manabi-memory-source.ts` para descobrir somente os projetos Claude já vinculados ao inventário (`folder_id` autorizado), localizar seus arquivos de sessão JSONL e ler incrementalmente por arquivo. Não fazer varredura irrestrita do disco. O adaptador de fonte registra a identidade do arquivo, posição do registro, inode ou equivalente disponível, tamanho e hash; detecta truncamento e rotação. Se o formato do Claude variar, a linha bruta continua preservável e o parser atribui `source_schema_version`; campos não reconhecidos não viram afirmações por suposição.

Criar `cli/src/lib/manabi-memory-spool.ts` com fila local durável em `~/.config/kioku/manabi/` (permissão 0700 no diretório, 0600 nos arquivos). Uma gravação atômica associa cada evento ao checkpoint. O checkpoint de leitura pode avançar depois que a linha entra no spool; o checkpoint de entrega só avança após `memory_ack`. Reinício envia os itens pendentes. O spool tem limite configurável, retenção e diagnóstico visível; ao atingir o limite, a leitura pausa sem perder a posição. Um agente que troca de computador não duplica eventos porque o servidor deduplica pelo ID.

`event_id = SHA256(source || user_id || folder_id || session_id || file_identity || record_position || content_hash)`. `event_time` vem do registro quando válido; `observed_at` é horário de leitura local; `ingested_at` é definido pelo banco. Ordenação usa posição por sessão, nunca só horário de ingestão. O caminho local não vai ao payload de recuperação; uma referência de origem pseudonimizada e metadados mínimos bastam.

O coletor separa `user`, `assistant`, `tool_result` e `external_text` como provenance distinta. Saída de ferramenta não recebe a mesma confiança de instrução explícita do usuário. O evento completo viaja em WSS autenticado para preservar a fonte; no backend, o conteúdo bruto é cifrado antes da gravação e uma cópia redigida é a única usada por Judge, embeddings, busca e MCP. A redação registra apenas contador e motivo, sem expor o valor. Não registrar conteúdo em logs. Eventos ilegíveis ou acima do limite geram diagnóstico com localização local e **não** um checkpoint silencioso; a recuperação do arquivo permanece possível. A primeira ativação começa em novas linhas por padrão; backfill histórico requer comando/consentimento explícito para controlar custo e privacidade.

### WebSocket

Adicionar ao `connect` existente um envelope de protocolo após `ready`:

```json
{"type":"memory_post","protocol":1,"event_id":"sha256-hex","content_hash":"sha256-hex","folder_id":"uuid","session_id":"opaque","source":"claude_code","source_schema_version":1,"record_position":123,"event_time":"2026-10-29T00:00:00Z","observed_at":"2026-10-29T00:00:02Z","provenance":"user","sensitivity":"normal","content":"..."}
```

Resposta de sucesso: `{"type":"memory_ack","event_id":"...","status":"stored|duplicate"}`. Erro recuperável: `memory_nack` com `retryable=true` e `retry_after_ms`; erro definitivo inclui código (`scope_denied`, `hash_conflict`, `invalid_payload`, `too_large`) e não avança o checkpoint até existir uma ação explícita de quarentena. `memory_post` é uma **mensagem pelo WebSocket**, não POST HTTP. Preservar `heartbeat` e `inventory`. Negociar suporte no `ready` (`capabilities:["memory_post_v1"]`) para Manabi antigo e backend antigo coexistirem durante rollout.

Limite inicial por mensagem: 64 KiB serializados, menor que o limite atual do backend. Um registro grande deve ser dividido em partes determinísticas ou ficar em quarentena local com aviso; a implementação de partes deve confirmar o evento completo antes de avançar entrega. Máximo de itens em voo por conexão, ack individual e reenvio após timeout evitam crescimento de memória. O servidor verifica `folder_id` contra o inventário autorizado do usuário e sua posse em `folders`; a credencial da máquina nunca autoriza outro usuário ou outra pasta.

## 2. Persistência e transações

Criar migração em `supabase/migrations/` com tabelas próprias do produto, `user_id` em todas as linhas, RLS habilitada e sem grants de escrita a clientes `anon`/`authenticated`. Backend e Mihari usam service role; MCP lê por funções com usuário e escopo explicitamente verificados. Índices compostos começam por `user_id` e `folder_id`. Os nomes abaixo são o contrato lógico; migração usa constraints, índices e RPCs SQL equivalentes.

| Tabela | Campos centrais | Chave / regra |
| --- | --- | --- |
| `memory_raw_events` | `event_id`, `user_id`, `folder_id`, `machine_id`, `source`, `session_id`, `record_position`, `raw_ciphertext`, `wrapped_dek`, `nonce`, `redacted_content`, `content_hash`, `event_time`, `observed_at`, `ingested_at`, `provenance`, `sensitivity` | PK `(user_id,event_id)`; conteúdo imutável; hash conflitante rejeitado |
| `memory_holding` | `user_id`, `event_id`, `state`, `attempts`, `lease_owner`, `lease_until`, `next_attempt_at`, `last_error_code` | Um item por evento; `QUEUED`, `LEASED`, `DONE`, `PENDING_REVIEW`, `DEAD_LETTER` |
| `memory_candidates` | `candidate_id`, `user_id`, `folder_id`, `assertion`, `scope`, `entity_keys`, `time_claims`, `state` | Ligação N:M com eventos brutos; candidato não é memória recuperável |
| `agent_memories` | `memory_id`, `user_id`, `folder_id`, `canonical_text`, `lifecycle`, `version`, `scope`, `branch`, `environment`, `valid_from`, `valid_to`, `confidence`, `superseded_by`, `merged_into`, `updated_at` | PK `(memory_id,version)`; lifecycle `ACTIVE`, `MERGED`, `SUPERSEDED`, `DISCARDED`; revisão antiga permanece |
| `memory_evidence` | `memory_id`, `version`, `event_id`, `span_start`, `span_end`, `evidence_role` | Toda ACTIVE tem ao menos uma evidência válida |
| `memory_relations` | `from_memory_id`, `to_memory_id`, `relation_type`, `decision_id` | Tipos `equivalent`, `complements`, `updates`, `contradicts` |
| `memory_decisions` | `decision_id`, `candidate_id`, `judge_version`, `policy_version`, `input_hash`, `outcome`, `confidence`, `rationale`, `evidence_refs`, `created_at` | Auditoria append-only; não guardar prompt bruto com segredo |
| `memory_index_outbox` | `memory_id`, `version`, `operation`, `state`, `attempts` | Upsert/delete de índice idempotente; mesma transação de lifecycle |
| `memory_scope_deltas` | `scope_id`, `sequence`, `memory_id`, `change_kind`, `affected_sections`, `created_at` | Sequência monotônica por escopo; dirty/watermark recuperáveis |
| `memory_summary_versions` | `scope_id`, `version`, `base_version`, `watermark`, `generated_at`, `sections`, `citations`, `status` | Snapshot publicado atomicamente, cinco seções em um JSON validado |

`memory_active_index` contém somente versões ACTIVE com texto para FTS e vetor persistente. Pode ser tabela separada de `agent_memories`; `DISCARDED` e `SUPERSEDED` não mantêm embedding. A RPC de consulta primeiro encontra IDs no índice e depois junta `agent_memories` exigindo `lifecycle='ACTIVE'`, versão igual e validade. Assim, a invalidação transacional é segura mesmo antes de um delete atrasado no índice. Uma outbox de delete falha mantém lixo físico temporário, nunca resultado corrente.

As operações críticas são RPCs transacionais em Postgres: `accept_memory_event`, `claim_memory_holding` com `FOR UPDATE SKIP LOCKED`, `commit_memory_decision`, `publish_memory_summary`. `commit_memory_decision` usa lock por `(user_id, scope, entity_key)` ou comparação otimista de versão e rejeita ciclos em `superseded_by`/`merged_into`. Lease expirado volta a ser elegível; backoff e dead letter são explícitos. Reprocessar com a mesma `policy_version`, `judge_version` e `input_hash` não cria outra transição.

O backend usa envelope encryption AES-256-GCM por evento; a DEK é protegida pelo KMS já empregado em `backend/services/crypto.py`. A função atual cifra somente segredos menores que 4 KiB, então ela **não** é aplicada diretamente ao JSONL bruto. O texto redigido é derivado antes de qualquer chamada de modelo. Falha de KMS/cifra impede commit e devolve nack recuperável, nunca grava plaintext. Acesso ao bruto requer função administrativa auditada; MCP e frontend nunca recebem `raw_ciphertext` ou DEK.

## 3. Pipeline de memória em Mihari

Separar módulos `mihari/memory/holding.py`, `extract.py`, `related.py`, `judge.py`, `commit.py`, `index.py` e `summary.py`; `mihari/mihari.py` apenas agenda os passes. O job de memória tem intervalo configurável separado de `MIHARI_SCHEDULE`, pequeno lote, limite de concorrência e timeout para não degradar fetch/indexação de repositórios. Um passe falho registra erro e retorna; o laço existente continua vivo.

1. **Claim e normalização:** selecionar eventos `QUEUED`/lease vencido, preservar fonte e tempos, limpar formato sem apagar o bruto.
2. **Extração:** agrupar registros semanticamente relacionados da mesma sessão e extrair afirmações atômicas. Linha de log não é automaticamente memória. Cada candidato guarda spans e IDs brutos. Não extrair segredo redigido nem instruções embutidas em conteúdo de terceiros como política.
3. **Relacionadas:** Top K `ACTIVE` no mesmo usuário e escopo, por FTS, vetor, entidade e tempo. Branch e ambiente são restrições, não apenas boosts. Se não houver candidato suficiente, ampliar busca dentro do escopo autorizado. Embedding temporário pode ajudar deduplicação e é descartado se o resultado não for ACTIVE.
4. **Judge:** saída JSON validada por schema com `outcome`, `relation_type`, `related_memory_ids`, `confidence`, `rationale`, `evidence_refs`, `valid_from/to`, `requires_review`, `judge_version`. Pesos de fonte favorecem correção do usuário, testes e fonte primária. Repetição não prova verdade. Triagem barata pode decidir ruído/duplicata clara; conflito, arquitetura ou baixa confiança vai para avaliação mais robusta ou `PENDING_REVIEW`. Limiares são calibrados com dataset rotulado, não valores arbitrários apresentados como qualidade.
5. **Commit:** nova informação útil cria ACTIVE; equivalente cria MERGED apontando à ACTIVE; atualização comprovada cria sucessora ACTIVE e encerra a anterior como SUPERSEDED; ruído cria DISCARDED; conflito inconclusivo permanece como candidato `PENDING_REVIEW`, sem memória indexada. Registrar a decisão, evidências, relações, versão e outbox atomicamente.
6. **Indexação:** processar outbox para ACTIVE; invalidação é imediatamente bloqueada na consulta por lifecycle. Falha no provedor de embeddings mantém item na outbox, com retry.

`event_time`, `ingested_at`, `valid_from` e `valid_to` não são intercambiáveis. Evento atrasado pode alterar uma linha histórica sem invalidar uma decisão mais nova. Uma memória por branch não substitui outra de branch distinto. `as_of` é consulta histórica separada, com indicação explícita de estado naquela data.

## 4. Living Summary

As seções são **Semantic**, **Episodic**, **Procedural**, **Preferences** e **Reflective**; são projeções, não categorias obrigatórias de cada memória. Um evento pode afetar zero ou várias. O estado inicial é vazio/mínimo.

Mihari mantém dirty por escopo e executa uma janela configurável independente da ingestão. A janela recebe o snapshot publicado, deltas desde o watermark, memórias ACTIVE afetadas, invalidações e evidências necessárias. O gerador produz um **snapshot lógico completo das cinco seções**, mesmo que internamente aplique patches. Publicação compara `base_version` e watermark em transação; se não houver mudança material, não grava versão. Vinte memórias na janela geram no máximo uma nova versão por escopo. Falha preserva snapshot anterior e dirty. Reconciliar periodicamente com ACTIVE e fontes originais para evitar drift de resumo sobre resumo.

Cada afirmação do summary carrega `supporting_memory_ids` e referências brutas. Antes da próxima janela, MCP pode servir a versão anterior somente se filtrar afirmações cujos IDs já não são ACTIVE; caso essa validação falhe, omite a seção afetada e mostra que atualização está pendente. Limites de tokens por seção e por escopo evitam transformar o contexto inicial em documento enorme. Expor `version`, `generated_at`, `watermark` e estado de atualização.

## 5. Recuperação, MCP e interface

Adicionar `backend/services/agent_memory/` para consulta ACTIVE e resolver de escopo. No `backend/mcp_server.py`, expor `get_memory_context(folder?)` para summary global curto + summary do projeto no início da sessão, `search_memories(query, folder?, component?, branch?, as_of?, limit?)` para detalhe sob demanda, e `get_memory_history(memory_id)` para histórico **explicitamente solicitado**. Sem `as_of`, nunca devolver SUPERSEDED/MERGED/DISCARDED. `as_of` usa caminho histórico próprio e rótulo “histórico, possivelmente não atual”. A API key limita a pasta raiz e seus descendentes como nas ferramentas MCP atuais; todas as consultas também filtram `user_id`.

Recuperação usa FTS + vetor de ACTIVE, fusão, rerank, relevância temporal contextual e diversidade de evidências. Fatos estáveis não sofrem decaimento uniforme. Resposta inclui ID, trecho curto, origem, tempo/validade, confiança, links de evidência e motivo de relevância. Respeitar orçamento de tokens e abster-se quando evidência não basta. Não misturar automaticamente memória e documentos no mesmo índice; podem ser recuperados em paralelo e apresentados com proveniência distinta.

Na interface, uma visualização de Memórias mostra primeiro as ACTIVE, com filtro por projeto e busca. Um painel por memória mostra fonte, confiança, validade, decisões e versões anteriores. Histórico é secundário, não uma lista de snapshots no briefing. Correção explícita do usuário pode propor uma nova versão com evidência forte, mas ainda passa pelo commit/auditoria. Exclusão de dados pessoais exige fluxo próprio de privacidade que remova conteúdo e embeddings derivados, preservando apenas tombstone sem texto sensível.

## 6. Observabilidade, limites e custo

Métricas mínimas: eventos lidos/enviados/confirmados/duplicados, idade do spool, tamanho do backlog, ack p50/p95, HOLDING por estado e idade, lease expirado, custo/tokens por extração/Judge/summary, decisões por outcome, erro de indexação, tempo até ACTIVE pesquisável, watermark e idade do summary, resultados inválidos barrados no read path, latência MCP p50/p95. Não colocar conteúdo de memória em logs ou tracing.

O limite de custo inicial é operacional: lote e concorrência configuráveis, triagem leve, decisão robusta apenas nos casos difíceis, summary por janela, no máximo um snapshot por escopo/janela, sem backfill automático. Medir custo por memória ACTIVE útil e por sessão beneficiada antes de aumentar volume. Métricas de qualidade com baseline sem memória: sucesso de tarefas, repetição de erro, precisão temporal, recall, confiança/calibração, custo e latência; sucesso isolado da tarefa não prova causalidade da memória.

## 7. Entregas incrementais e portas de saída

| Fase | Mudanças principais | Critério para avançar |
| --- | --- | --- |
| 0. Contrato e dados | Migração, RPCs, schemas Pydantic/TypeScript, capability handshake; flags desligadas | Migração/rollback testados e nenhuma regressão de presença Manabi |
| 1. Captura | `manabi-memory-source`, spool, `memory_post/ack`, HOLDING | Reenvio é idempotente; kill/restart não perde evento confirmado; falha de rede não bloqueia sessão |
| 2. Lifecycle | Polling Mihari, extração, Judge, transações e auditoria | Atualização invalida anterior; conflito inconclusivo não vira ACTIVE; replay não duplica |
| 3. Retrieval | Índice ACTIVE, FTS/vetor, filtros e MCP sob demanda | SUPERSEDED nunca aparece na busca atual, inclusive com outbox atrasada; `as_of` mostra histórico correto |
| 4. Summary | Dirty, janela, cinco seções, publicação atômica e reconstrução | 20 memórias geram no máximo 1 snapshot; sem delta, 0; falha não perde delta |
| 5. Experiência | Contexto inicial, painel de memória/histórico, correção/feedback | Agent recebe contexto curto; usuário vê fonte e revisão sem briefing inflado |
| 6. Qualidade | Dataset rotulado, calibração, métricas e reconciliação | Avaliação compara baseline sem memória e limita regressão de custo/latência |

Habilitar por flags independentes por usuário: `capture`, `judge`, `retrieve`, `summary`, `session_context`. Primeiro rodar shadow mode com eventos reais autorizados, decisões não publicadas e auditoria. Depois ativar por pequena coorte e medir. A migração de bancos precede backend; backend que entende o protocolo precede CLI/Manabi; Mihari só faz claim quando as tabelas existem. Rollback desativa flags e preserva bruto/decisões; não apaga conteúdo sem solicitação explícita.

### Testes de contrato indispensáveis

- WebSocket: autenticação, propriedade de pasta, ack após commit, duplicata com mesmo hash, conflito de hash, timeout/reconnect, mensagens legadas e limite de payload.
- Manabi: linha parcial, rotação/truncamento, reinício entre spool e ack, backpressure, arquivo ilegível, ausência de projeto autorizado e conteúdo com segredo.
- Banco: dois workers concorrentes, lease expirado, optimistic lock, transição ACTIVE→SUPERSEDED, MERGED→destino, outbox atrasada, replay idempotente, cross-user/cross-folder negado.
- Judge: evidência ausente, usuário contradiz agente, duas branches divergentes, evento antigo recebido depois do novo, conteúdo malicioso em tool result, conflito sem prova.
- Summary: dirty em várias seções, snapshot completo atômico, CAS falho, janela vazia, reconstrução de ACTIVE, referência invalidada omitida antes da próxima janela.
- MCP: orçamento, citação, abstenção, escopo, `as_of`, versão histórica sinalizada e nenhuma memória invalidada no modo corrente.

## Fora do primeiro corte

Fine-tuning, knowledge graph obrigatório para memórias, embeddings de descartadas/superadas, reprocessamento completo a cada atualização, suporte automático a todas as fontes de agente e promessa de ganho sem avaliação. O primeiro adaptador de captura é Claude Code; o contrato `source` permite adicionar Codex depois sem mudar lifecycle.

## Decisões de produto preservadas

Esta implementação mantém briefing e arquivos sem histórico na experiência principal. O histórico aparece por memória porque correção, precedência temporal e proveniência são parte do valor do sistema. Manabi continua o serviço local existente e Mihari continua o worker cloud; nenhuma terceira fila/processo de aplicação é introduzida. A semântica de `HOLDING` é estado de processamento, não lifecycle da memória.
