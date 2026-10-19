# Shock Stream 0.6.0 — internet pelos aplicativos

Esta versão acrescenta um servidor privado de conexão e integra seu uso ao Windows e ao iPad iOS 9 ARMv7. **O servidor está pronto para instalar, mas não existe uma hospedagem pública configurada neste projeto.** Sem hospedagem, o modo por servidor não alcança PCs fora da rede local. USB, Wi-Fi e acesso TLS direto 0.5.0 continuam disponíveis.

## Depois da configuração inicial

1. Abra o Shock Stream no PC e inicie a transmissão.
2. Na primeira utilização, o administrador cola a configuração `shockrelay://…` no campo **Internet automática por servidor**. Clique **Ativar / convite + QR**.
3. No iPad atualizado, selecione **Remoto → Ler QR do PC**. Também pode colar o convite completo. Esse convite é uma credencial de controle; compartilhe apenas com quem poderá controlar o PC.
4. Após aceitar a sessão, o iPad guarda o convite no Keychain quando permitido pelo sistema. O modo Remoto é lembrado. Nas próximas aberturas, tenta conectar automaticamente. Se o Keychain recusar salvar no jailbreak utilizado, o convite terá de ser lido/colado novamente; o aplicativo registra um aviso sem revelar a credencial.
5. O PC guarda a opção de reconectar ao servidor ao iniciar o app. Para isso, também mantenha **Ficar pronto para conectar ao abrir este programa** ativada. **Desativar** encerra o acesso remoto e desmarca sua reconexão. **Revogar convites remotos** invalida chave, endereço lógico e credencial de conexão anteriores; leia um QR novo para autorizar novamente.

O PC precisa estar ligado, com sessão aberta, internet e o programa em execução. O iPad precisa do app em primeiro plano. Não há abertura de portas no roteador doméstico, aplicativo VPN separado, descoberta pela internet pública ou desbloqueio remoto do PC/iPad. Uma sessão de controle por vez é compartilhada por todos os transportes. A revogação desta versão invalida todos os convites desse PC; não existe um cadastro de usuários com revogação individual.

## Instalar o servidor em uma VPS Linux

É necessário um servidor Linux com IP público alcançável e Docker com Compose. Um domínio é opcional: pode usar IP público estável. Hospedagem que fornece somente páginas/HTTP e não permite serviço TCP persistente não atende ao protocolo atual. A liberação TCP 443 é feita no firewall **do servidor**, não no roteador da casa. Não há compra, contratação ou hospedagem incluída nos aplicativos.

Copie a pasta `pc-ipad` do repositório para o servidor, mantendo `relay/` e `windows/remote.py`. Entre em `pc-ipad/relay`:

```sh
docker compose build
docker compose run --rm relay --setup SEU_IP_PUBLICO_OU_DNS:443
docker compose up -d
docker compose run --rm --entrypoint cat relay /data/configurar-pc.txt
```

O último comando mostra a configuração privada para colar **somente no PC administrador**. Ela autoriza registrar o PC nesse servidor. Não a envie ao iPad nem publique esse texto. O iPad recebe o convite/QR próprio gerado pelo programa Windows, sem a credencial administrativa.

O Compose publica 443 → 8443, executa sem root com permissões reduzidas, sistema de arquivos somente leitura e volume persistente. O volume guarda certificado/chave do servidor e autorização administrativa. Preserve-o nas atualizações: recriar sua identidade exige configurar o PC e emparelhar o iPad novamente. Faça backup privado desse volume. Reinício do serviço usa `docker compose restart`; manutenção/atualização usa `docker compose up -d --build`, preservando o volume. Não use `down -v` numa atualização normal.

Alternativa sem Docker: instale Python 3.12 e `cryptography==46.0.3`, depois execute `python relay/server.py --data CAMINHO_PRIVADO --port 8443`. Gere a configuração com `--setup HOST_PUBLICO:PORTA_PUBLICA`. Configure o serviço do sistema e o encaminhamento da porta pública para 8443; não é preciso executar Python como root para escutar 8443. Nunca hospede dentro do GitHub Actions: os runners deste projeto servem somente para build/testes temporários.

## Proteção e limites

PC e iPad fazem conexões de saída para o servidor. Há duas camadas de TLS: cada app confere o certificado exato do servidor; dentro do túnel, o iPad confere também o certificado do PC e autentica com sua chave de 256 bits. O servidor encaminha os bytes da camada interna e não recebe sua chave de autenticação nem o vídeo decodificado. Mesmo possuindo o certificado do relay, ele não consegue se passar pelo PC sem a chave privada correspondente ao certificado fixado do PC.

O administrador é autenticado para registrar um PC; o iPad precisa de endereço lógico e credencial aleatórios para solicitar a conexão. Registros duplicados são recusados. Requisições têm tamanho/tempo limitados, tentativas recusadas são limitadas por IP, e conexões/PCs simultâneos são limitados. O relay não abre conexões para endereços arbitrários informados pelo cliente. Ele pode observar horários, volume de tráfego e endereços IP das conexões, e pode interromper o serviço; criptografia não garante disponibilidade de uma hospedagem maliciosa ou indisponível.

As cópias usam blocos limitados e controle de fluxo. O vídeo conserva um frame em trânsito e descarta capturas antigas antes de codificar, sem acumular uma fila de vídeo. O servidor intermediário acrescenta percurso de rede; escolha futuramente uma região próxima aos aparelhos. Upload do PC, rede do iPad e capacidade do servidor determinam o resultado. Comece com **Economizar rede**, 20 FPS e áudio desligado se necessário. Redes corporativas com proxy obrigatório podem bloquear este protocolo, apesar da porta 443. Não existe garantia de conexão em qualquer rede ou de latência idêntica ao USB.

Esta entrega usa encaminhamento pelo servidor. Não implementa negociação P2P/ICE, contas públicas, lista de aparelhos autorizados ou adaptação automática de bitrate. A qualidade pode ser alterada no PC durante a sessão pelos controles existentes.

## Verificação

Os testes usam um relay TLS real local, conexão de saída do host e uma segunda camada TLS entre cliente e PC. Cobrem autenticação, transmissão de vídeo/controle, reconexão, revogação e recusa de credenciais/certificados incorretos. O CI macOS testa também o transporte Secure Transport nativo com as duas camadas TLS e envio simultâneo de controles. O CI Linux constrói o container e verifica o provisionamento em volume persistente. Builds não substituem teste físico no iPad mini 1 nem teste entre redes reais. A câmera/Keychain dependem do sistema e jailbreak instalados.

Referências: [Python SSL/Memory BIO](https://docs.python.org/3/library/ssl.html), [Apple Secure Transport](https://developer.apple.com/library/archive/technotes/tn2232/_index.html).
