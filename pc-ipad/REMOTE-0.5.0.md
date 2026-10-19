# Shock Stream 0.5.0 — acesso remoto

Atualize Windows e iPad para 0.5.0. Os modos Wi-Fi local e USB mantêm o protocolo existente. O novo modo **Remoto** transmite vídeo, áudio e os controles touch/gamepad pela mesma sessão, sobre TLS 1.2 ou superior. Usa uma chave aleatória de 256 bits separada do PIN local e confere o SHA-256 do certificado exato do PC antes de enviar a prova de acesso. A implementação do iPad usa Secure Transport, disponível no SDK iOS 9.2 usado pelo projeto; não depende de navegador moderno ou aplicativo VPN recente.

## Configurar

1. No PC, abra o programa, selecione a tela e clique **Iniciar**. Pode escolher monitor principal ou virtual, touch ou gamepad.
2. Para acesso direto, reserve o IP local do PC no roteador e encaminhe uma porta TCP externa para a porta **8093** desse PC. Permita TCP 8093 de entrada no Firewall do Windows para a rede utilizada. **Não encaminhe 8090**, que continua sendo o transporte local sem TLS. O programa não modifica roteador, Firewall ou regras de segurança automaticamente.
3. No campo **Acesso remoto**, informe o IP público ou DNS e a porta externa. Exemplo de formato: `seu-endereco-publico:8093`. Se encaminhar a porta externa 443 para a interna 8093, informe `seu-endereco-publico:443`.
4. Clique **Ativar / copiar convite**. Transfira o texto completo do convite para o iPad por um meio privado. O convite contém credencial de acesso ao PC: quem o possui pode controlar a tela enquanto o modo remoto estiver ativo.
5. No iPad atualizado, selecione **Remoto**, cole o convite no campo de endereço e toque **Conectar / emparelhar**. O PIN de seis dígitos não é utilizado nesse modo. Após uma conexão aceita, o convite é lembrado separadamente do pareamento local. Na próxima abertura, selecione Remoto para reutilizá-lo.
6. **Desativar** fecha o acesso remoto e sua sessão atual sem parar a espera por Wi-Fi/USB. **Revogar convites remotos** também troca a chave, invalidando todos os convites anteriores. Copie um novo convite para autorizar novamente. Fechar e reabrir o programa exige ativar o remoto novamente.

## CGNAT, túneis e limites

Se a operadora usa CGNAT, encaminhar portas no roteador doméstico não basta. Solicite um IP público à operadora ou configure um túnel **TCP transparente** do PC para um servidor público. Ele deve encaminhar o tráfego para `127.0.0.1:8093`, preservando o TLS de ponta a ponta. Nesse caso o convite aponta para o endereço/porta do túnel. Um proxy HTTP comum não substitui o túnel TCP deste protocolo. Nenhum servidor intermediário ou conta de terceiros é criado por este aplicativo.

O host escuta IPv4 na porta interna 8093. O cliente resolve nomes DNS e pode alcançar um endereço IPv6 externo quando um túnel encaminha para o host IPv4. Descoberta automática Bonjour/broadcast continua limitada à rede local; não existe busca de computadores aleatórios pela internet. O PC precisa estar ligado, com sessão de usuário aberta e o programa executando. Este modo não liga o PC remotamente e não contorna bloqueios de rede.

Há somente uma sessão de controle por vez, compartilhada entre USB, Wi-Fi e remoto. O modo remoto conserva a fila de um frame e o ACK, sem acumular vídeo; a distância, o upload do PC e a rede móvel influenciam a resposta. Comece com **Economizar rede**, 20 FPS e áudio desligado se a conexão oscilar. Não é possível garantir latência de LAN na internet.

## Identidade e armazenamento

Certificado/chave privada e chave de acesso são persistidos em `%LOCALAPPDATA%/ShockStream/remote/`, dentro do perfil do usuário Windows. O certificado exato do convite é a âncora de confiança, sem aceitar qualquer certificado nem depender das autoridades antigas do iOS 9. Não apague `identity.pem` para uma atualização normal: trocar o certificado exige novos convites. A chave remota não é anunciada por Bonjour/UDP, não é incluída no pacote e não é o PIN nem a chave do auxiliar USB. Convites e credenciais não são escritos nos logs.

O app iOS usa o Keychain para lembrar o convite remoto; a migração preserva o pareamento Wi-Fi/USB existente. Como nos pacotes anteriores, o iPad usa assinatura ad-hoc para o método com jailbreak do projeto, sem perfil de distribuição Apple. O build é crescente e o identificador do aplicativo é mantido.

## Validação

Testes automatizados cobrem persistência e revogação, convites inválidos, certificado incorreto, recusa do PIN local no acesso remoto, autenticação TLS, geometria inicial e eventos touch, tráfego bidirecional e preservação do listener local ao desativar remoto. O CI também compila o transporte nativo Apple e testa sua comunicação real contra o servidor TLS Python, incluindo leitura de vídeo simultânea ao envio de controles. O teste físico entre duas redes e no iPad mini 1 continua necessário; um build aprovado não confirma alcance através do seu roteador/operadora.

Referências técnicas: [Apple: avaliação de confiança TLS](https://developer.apple.com/library/archive/technotes/tn2232/_index.html), [Apple: pausa para autenticar o servidor](https://developer.apple.com/documentation/security/sslsessionoption/breakonserverauth), [Cryptography: certificados X.509](https://cryptography.io/en/stable/x509/tutorial/).
