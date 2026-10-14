# Shock Stream 0.3.0 · monitor touch e gamepad

O programa Windows 11 transmite a área de trabalho para o iPad mini 1, iOS 9 / ARMv7. O IPA usa a instalação por Filza no ambiente com jailbreak já utilizado no projeto.

## Começar

1. Atualize **os dois aplicativos**. Descompacte o ZIP do Windows mantendo ShockStream.exe e _internal juntos; instale o novo IPA no iPad.
2. Abra o programa no PC. O padrão é **Automático · Wi-Fi + USB** com **Monitor touch · tela livre**. Ele fica pronto ao abrir; essa opção pode ser desmarcada.
3. Abra o app no iPad. Na mesma rede Wi-Fi, ele procura o PC e preenche o endereço automaticamente. Não é necessário reservar IP fixo no roteador.
4. Informe o PIN exibido no PC uma vez e toque **Conectar / emparelhar**. O PC mantém sua identidade/PIN entre aberturas; o iPad salva o pareamento apenas após receber uma sessão autenticada válida.
5. Nas próximas aberturas, o iPad tenta o PC conhecido pelo Wi-Fi e pelo USB. A primeira conexão aceita ocupa a sessão. Ao perder a conexão, procura novamente. Para usar somente o cabo ou somente Wi-Fi, selecione esse transporte nos dois aplicativos.

O app do PC precisa estar aberto. No iPad, o app precisa estar em primeiro plano; ligar o cabo sozinho **não abre automaticamente o app do iOS**. A busca e conexão automáticas acontecem com os apps abertos, após o primeiro pareamento. Ao voltar pelo botão Home, o iPad fecha a conexão; ao reabrir, retoma a busca. Não há serviço ADB.

Se a rede bloquear multicast/Bonjour, existe o campo de IP manual. Permita o aplicativo na rede privada do Firewall do Windows quando solicitado: vídeo/controles usam TCP 8090; descoberta Bonjour usa UDP 5353. O programa não altera o Firewall sozinho. A descoberta anuncia identidade/nome/endereço/porta, nunca o PIN. Na troca de IP, o host reanuncia as interfaces e o iPad busca os endereços atuais.

## Touch sem cobrir a imagem

**Monitor touch · tela livre** funciona tanto no Wi-Fi quanto no USB e não precisa do ViGEmBus. Não há botões nem gamepad sobrepostos. Toques curtos, arrastes, up e cancel usam InjectTouchInput nativo no Windows, com até dez contatos. A coordenada é calculada a partir da imagem exibida e do retângulo real da tela escolhida, inclusive telas com posição negativa.

Para sair, pressione Home no iPad ou **Parar** no PC. Rotação, desconexão e perda de atualização cancelam os contatos para evitar dedos presos. Programas elevados e sistemas anticheat podem impor limites ao input injetado.

Para jogar com controle na tela, escolha **Gamepad virtual na tela** no PC. O iPad recebe esse modo automaticamente. O botão **Instalar gamepad** abre o instalador oficial ViGEmBus incluído. O controle oferece dois sticks, direcional, A/B/X/Y, ombros/gatilhos, L3/R3 e START/BACK. Somente uma sessão controla o PC por vez.

## Toda a tela do iPad

Use **Criar segundo monitor** no programa Windows e selecione **Monitor virtual** em Tela transmitida. Em uma configuração nova, o driver incluído oferece 1024×768 e 768×1024 a 60 Hz. O host ajusta somente esse monitor virtual à orientação informada pelo iPad, testa o modo antes de aplicar e captura a resolução nativa do tablet. Não aumenta a transmissão além de 1024×768 / 768×1024.

A tela física do PC conserva sua configuração. Se você escolher espelhar uma tela física de proporção diferente, a imagem mantém a proporção e pode ter barras. Para ocupar a tela inteira sem distorção, escolha o monitor virtual de proporção 4:3. É possível arrastar janelas para ele no Windows, como em um segundo monitor.

A troca de orientação reinicia o encoder com novos SPS/PPS H.264. A confirmação de geometria identifica a solicitação mais recente do iPad antes de reativar touch. Mudanças de posição/resolução feitas no Windows também são detectadas. Qualidade reduzida de 800/640 px e 20/15 FPS continuam disponíveis; o padrão é 1024 px e 30 FPS.

O driver exige autorização do Windows para instalar/remover. O helper gerencia somente Root\MttVDD; não modifica a imposição de assinatura de drivers. Uma configuração de driver já existente é preservada: se não oferecer as duas resoluções, o programa informa e mantém a captura proporcional. O botão **Estender área de trabalho** permite solicitar a extensão novamente.

## USB

Use um cabo de dados e confirme **Confiar neste computador** no iPad, se aparecer. No primeiro uso, **Preparar USB Apple** verifica o serviço; se faltar, o Windows Package Manager abre a instalação oficial do iTunes/suporte Apple. Precisa de internet nessa preparação. O programa verifica novamente o serviço após instalar, distingue serviço ausente de aparelho ausente e atualiza a lista. Os binários proprietários da Apple não são redistribuídos no ZIP.

No modo automático, um único aparelho conectado é selecionado sem clicar em Detectar. Se houver vários aparelhos Apple, pare a transmissão, atualize a lista e selecione o iPad desejado. A identidade serial acompanha mudanças de DeviceID ao reconectar.

O cliente usbmux aceita plist ListDevices, eventos Listen/Attached e protocolo binário v0 usado por serviços Apple antigos. O serviço local do PC é 127.0.0.1:27015; o app do iPad abre 127.0.0.1:8091. Não há iproxy separado. No primeiro pareamento exclusivamente por cabo, informe o PIN no iPad e toque Conectar; depois o listener abre automaticamente com o PIN salvo.

Se continuar sem reconhecimento, confira o cabo, Confiar e o Apple Mobile Device Service. O log em %LOCALAPPDATA%/ShockStream/host.log e a mensagem da interface ajudam a distinguir serviço, aparelho e porta do app. Nenhum diagnóstico publica o PIN ou número de série.

## Vídeo e build

H.264 Constrained Baseline por CPU/libx264, sem B-frames, com VideoToolbox no iPad. A captura sobrescreve um único frame bruto. O host espera ACK de decodificação/apresentação antes de codificar o próximo; não descarta pacotes H.264 dependentes nem acumula uma fila de frames atrasados. Áudio de loopback WASAPI, PCM estéreo 44,1 kHz, usa filas limitadas e pode ser desativado.

Wi-Fi autentica desafio HMAC/PIN mas não criptografa a transmissão; use uma rede local de confiança. O serviço não deve ser exposto à internet. Não há encoder GPU, rumble ou catálogo de jogos nesta versão.

O GitHub Actions compila Windows x64 e IPA iOS 9 ARMv7, roda testes de protocolo/codec/input/túneis simulados e verifica o executável empacotado sem instalar drivers ou injetar touch real no runner. O IPA mantém o bundle ID e CFBundleVersion crescente; a assinatura ldid tem hashes de código verificados e depende do ambiente com jailbreak, sem provisionamento Apple. Drivers oficiais incluídos têm downloads fixados por hash e assinatura verificada no build. O executável/helper próprios não têm certificado comercial.

O usuário confirmou o streaming Wi-Fi da versão anterior. Descoberta, USB, rotação e touch desta versão ainda requerem teste com o iPad e cabo físicos; testes automatizados e build não substituem essa validação. A latência física não foi medida.

Para desenvolvimento, instale windows/requirements.txt e execute scripts/install_gamepad.py em ambiente isolado. Rode python -m unittest discover -s pc-ipad/tests -v. Dependências e licenças acompanham o pacote em THIRD_PARTY.md e licenses/.
