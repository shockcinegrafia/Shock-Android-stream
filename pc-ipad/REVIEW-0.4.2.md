# Revisão da versão 0.4.1 e correções 0.4.2

O ZIP Windows 0.4.1 confere com o SHA256 informado pelo Antigravity. O código mudou nos dois clientes, mas os arquivos IPA/DEB continuavam sendo os da versão 0.4.0/build 9. Validar a assinatura desses arquivos antigos não compila nem valida o código iOS novo. A descoberta UDP e o tratamento novo de orientação exigem instalar o cliente iPad atualizado. A compatibilidade básica de protocolo com 0.4 foi mantida; isso não fornece funções que não existem no binário antigo.

## Achados e mudanças

- **Descoberta iPad sem validação:** o callback recebia diretamente campos JSON sem conferir os tipos de hostId, port e name. Arrays/NSNull podiam chegar ao controlador, que espera strings e números, e provocar exceções. O parser nativo agora limita o pacote a 1024 bytes, valida identidade hexadecimal, porta inteira e nome, e cria um dicionário completo usando o endereço do remetente. Endereços fornecidos pelo JSON não redirecionam a conexão. A descoberta não substitui a autenticação PIN/HMAC da sessão.
- **Socket e ciclo de vida:** o socket era fechado imediatamente após dispatch_source_cancel, enquanto o handler podia ainda estar lendo na fila de background. Agora a leitura é não bloqueante, serializada na fila principal, e o descriptor só fecha no cancellation handler. A geração da busca impede callbacks antigos após stop/start. Isso segue a documentação Apple de Dispatch Sources: https://developer.apple.com/library/archive/documentation/General/Conceptual/ConcurrencyProgrammingGuide/GCDWorkQueues/GCDWorkQueues.html .
- **Rotação e input:** o tamanho de destino podia ser enviado com a orientação antiga, e um INFO anterior podia reativar o touch durante a animação. A transição agora neutraliza input, bloqueia novos eventos e só publica a geometria final ao concluir. A liberação depende da confirmação do displayId atual. A notificação também cobre rotações de 180 graus; o teste físico dessas transições continua necessário.
- **Teste UDP interferindo com o programa:** a suíte 0.4.1 falhou nesta revisão porque o teste abria UDP 8090 e recebia a resposta do host real em execução. O teste usa agora uma porta efêmera exclusiva, sem Bonjour e sem interferir no programa. Testa também sondas inválidas, fechamento e nova abertura. O responder de produção usa UDP 8090, separado da porta TCP anunciada, e só responde à sonda exata SHOCK_DISCOVER_V1.
- **Cancelamento de contatos:** foi preservada a tentativa de liberar os demais contatos após uma falha. O teste agora verifica realmente a tentativa de cancelar o segundo dedo. Erros deixam registro no log em vez de desaparecer silenciosamente. Limpar o estado local não garante que uma API que recusou o cancelamento tenha executado o gesto. A API Windows pode também cancelar todos os contatos em determinados erros: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-injecttouchinput .
- **Versão:** o host ainda declarava 0.4.0 apesar do nome 0.4.1 do ZIP, e o Info.plist não havia sido atualizado. Host/app passam a 0.4.2; CI incrementa o build iOS e usa o mesmo build no DEB, sem trocar bundle ID ou permissões.

## O que o relatório anterior não demonstra

`min(0.005, max(0.001, deadline - now))` varia entre 1 e 5 ms, não é sub-milissegundo. Event.wait já acorda quando o ACK chega; não há uma pausa obrigatória de 5 ms após cada frame. Foi mantida a espera orientada por evento e limitado o timeout ao prazo restante. Não houve medição de latência física, nem evidência suficiente para anunciar redução de milissegundos: https://docs.python.org/3/library/threading.html#event-objects .

A presença de nomes de bibliotecas, mensagens e constantes nos binários do spacedesk é evidência estática. Não comprova, sozinha, que todos os clientes usam o mesmo framing, que ACK corresponde à apresentação na tela ou que há um número específico de drivers de kernel obrigatórios. Não foi demonstrada interoperabilidade com um cliente spacedesk. A ausência do binário iOS limita a análise, mas não prova a impossibilidade geral de reimplementar um protocolo. Não foram copiadas bibliotecas ou drivers proprietários para o Shock Stream.

As funções de descoberta e orientação são melhorias próprias e úteis, com validação descrita separadamente. Broadcast também pode ser bloqueado pela rede; não se promete descoberta imediata ou funcionamento universal.

## Validação

Após as correções, 129 testes Python terminaram sem falhas nesta máquina; 7 foram ignorados por dependerem de shell POSIX/dpkg no Linux, e não por exigir hardware físico. Foi adicionado teste nativo Objective-C para validar o parser real de descoberta no macOS. O workflow executa esse teste, os 16 testes de pacote em Linux, o teste do auxiliar e as compilações Windows/iOS. A aprovação do build e os arquivos finais devem ser conferidos no run associado à entrega.

O usuário já confirmou USB/Wi-Fi de versões anteriores, instalação/abertura do DEB 0.4 e resposta física do auxiliar USB. Descoberta broadcast, rotação completa, touch e abertura automática da versão 0.4.2 ainda precisam de validação no iPad físico. Não se afirma preservação de 100% da funcionalidade sem esse teste.
