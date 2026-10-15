# Shock Stream 0.4.0 · monitor touch, USB e gamepad

O programa Windows 11 transmite uma tela do computador para o iPad mini 1, iOS 9 / ARMv7. O pacote **.deb rootful** instala o aplicativo e um auxiliar para solicitar sua abertura pelo USB. O **.ipa** continua disponível para instalação pelo método com jailbreak já utilizado no projeto, com conexão automática enquanto o app está aberto.

## Começar

1. Atualize **os dois aplicativos**. Descompacte o ZIP do Windows mantendo ShockStream.exe e _internal juntos. Para usar a abertura pelo cabo, instale o .deb no iPad com jailbreak ativo. **Se já houver o IPA do ShockStream, remova-o manualmente antes:** os dois usam o mesmo bundle ID. O instalador recusa a duplicidade e não apaga o IPA nem seus dados automaticamente. A troca de formato não garante migração do pareamento; esteja preparado para informar o PIN novamente.
2. Abra o programa no PC. O padrão é **Automático · Wi-Fi + USB** com **Monitor touch · tela livre**. Ele fica pronto ao abrir; essa opção pode ser desmarcada.
3. Abra o app no iPad. Na mesma rede Wi-Fi, ele procura o PC e preenche o endereço automaticamente. Não é necessário reservar IP fixo no roteador.
4. Informe o PIN exibido no PC uma vez e toque **Conectar / emparelhar**. O PC mantém sua identidade/PIN entre aberturas; o iPad salva o pareamento apenas após receber uma sessão autenticada válida.
5. Nas próximas aberturas, o iPad tenta o PC conhecido pelo Wi-Fi e pelo USB. A primeira conexão aceita ocupa a sessão. Ao perder a conexão, procura novamente. Para usar somente o cabo ou somente Wi-Fi, selecione esse transporte nos dois aplicativos. No .deb, o primeiro pareamento válido também prepara a abertura USB automática; o botão no iPad permite desativá-la ou ativá-la novamente.

O programa do PC precisa estar em execução, inclusive quando fica na bandeja. **No Wi-Fi, a descoberta e o streaming exigem o app do iPad aberto em primeiro plano.** No USB, o .deb permite ao PC solicitar a abertura do app depois do pareamento, com o auxiliar ativo e a opção habilitada. Essa abertura usa recursos do iOS com jailbreak e ainda precisa de validação física no iPad mini 1; instalar o pacote não garante que o iOS aceite todas as solicitações. Não há serviço ADB.

## Windows na bandeja

Com o ícone do ShockStream disponível na bandeja, fechar a janela pelo X mantém o programa em execução. O menu oferece **Abrir Shock Stream**, **Retomar iPad pelo USB**, **Parar transmissão** e **Sair completamente**. O botão **Sair** da janela também encerra o programa; **Parar** encerra a transmissão e a espera por conexões.

**Iniciar com o Windows e ficar na bandeja** é uma opção que o usuário precisa marcar. Ela inicia o programa no login desse usuário, sem instalar um serviço do Windows. Mantenha a pasta do programa no mesmo local; se movê-la, desmarque e marque a opção novamente a partir da nova pasta. A opção separada **Ficar pronto para conectar ao abrir este programa** controla o início da espera por conexões.

## Descoberta pela rede local

Se a rede bloquear multicast/Bonjour, existe o campo de IP manual. Permita o aplicativo na rede privada do Firewall do Windows quando solicitado: vídeo/controles usam TCP 8090; descoberta Bonjour usa UDP 5353. O programa não altera o Firewall sozinho. A descoberta anuncia identidade/nome/endereço/porta, nunca o PIN. Na troca de IP, o host reanuncia as interfaces e o iPad busca os endereços atuais.

## Touch sem cobrir a imagem

**Monitor touch · tela livre** funciona tanto no Wi-Fi quanto no USB e não precisa do ViGEmBus. Não há botões nem gamepad sobrepostos. Toques curtos, arrastes, up e cancel usam InjectTouchInput nativo no Windows, com até dez contatos. A coordenada é calculada a partir da imagem exibida e do retângulo real da tela escolhida, inclusive telas com posição negativa.

Para sair, pressione Home no iPad ou **Parar** no PC. Rotação, desconexão e perda de atualização cancelam os contatos para evitar dedos presos. Se o Windows recusar a injeção de um toque, o host cancela os contatos e informa um aviso recuperável; o vídeo pode continuar e o usuário pode tentar um novo gesto. O último aviso aparece em **Diagnóstico / copiar** no iPad. Programas elevados e sistemas anticheat podem impor limites ao input injetado.

Para jogar com controle na tela, escolha **Gamepad virtual na tela** no PC. O iPad recebe esse modo automaticamente. O botão **Instalar gamepad** abre o instalador oficial ViGEmBus incluído. O controle oferece dois sticks, direcional, A/B/X/Y, ombros/gatilhos, L3/R3 e START/BACK. Somente uma sessão controla o PC por vez.

## Toda a tela do iPad

Use **Criar segundo monitor** no programa Windows e confirme **Monitor virtual** em **Tela transmitida**. Após instalar e ativar o driver, o programa procura e seleciona essa tela. Em uma configuração nova, o driver incluído oferece 1024×768 e 768×1024 a 60 Hz. O host ajusta somente esse monitor virtual à orientação informada pelo iPad, testa o modo antes de aplicar e captura a resolução nativa do tablet. Não aumenta a transmissão além de 1024×768 / 768×1024.

**Nova área de trabalho**, na Visão de Tarefas do Windows, organiza janelas em outro desktop e não cria uma segunda tela para o iPad. É necessário o monitor do driver, visível também nas configurações de exibição do Windows. **Verificar monitor** distingue driver ausente, adaptador instalado sem tela ativa e monitor ativo. **Estender área de trabalho** tenta ativar um monitor virtual instalado e inativo, mantendo a tela principal. Se o driver não publicar uma tela, a mensagem orienta reparar a instalação ou reiniciar o PC.

A tela física do PC conserva sua configuração. Se você escolher espelhar uma tela física de proporção diferente, a imagem mantém a proporção e pode ter barras. Para ocupar a tela inteira sem distorção, escolha o monitor virtual de proporção 4:3 na horizontal, ou 3:4 na vertical. É possível arrastar janelas para ele no Windows, como em um segundo monitor. Alterar **Tela transmitida** durante a sessão faz o programa encerrar e reiniciar a captura na nova seleção.

A troca de orientação reinicia o encoder com novos SPS/PPS H.264. A confirmação de geometria identifica a solicitação mais recente do iPad antes de reativar touch. Mudanças de posição/resolução feitas no Windows também são detectadas. Qualidade reduzida de 800/640 px e 20/15 FPS continuam disponíveis; o padrão é 1024 px e 30 FPS.

O driver exige autorização do Windows para instalar/remover. O helper gerencia somente Root\MttVDD; não modifica a imposição de assinatura de drivers. Uma configuração de driver já existente é preservada: se não oferecer as duas resoluções, o programa informa e mantém a captura proporcional. O botão **Estender área de trabalho** permite solicitar a extensão novamente.

## USB

Use um cabo de dados e confirme **Confiar neste computador** no iPad, se aparecer. No primeiro uso, **Preparar USB Apple** verifica o serviço; se faltar, o Windows Package Manager abre a instalação oficial do iTunes/suporte Apple. Precisa de internet nessa preparação. O programa verifica novamente o serviço após instalar, distingue serviço ausente de aparelho ausente e atualiza a lista. Os binários proprietários da Apple não são redistribuídos no ZIP.

No modo automático, um único aparelho conectado é selecionado sem clicar em Detectar. Se houver vários aparelhos Apple, pare a transmissão, atualize a lista e selecione o iPad desejado. A identidade serial acompanha mudanças de DeviceID ao reconectar.

O cliente usbmux aceita plist ListDevices, eventos Listen/Attached e protocolo binário v0 usado por serviços Apple antigos. O serviço local do PC é 127.0.0.1:27015; o app do iPad abre 127.0.0.1:8091 para streaming. O auxiliar do .deb escuta somente 127.0.0.1:8092 no iPad para pedidos autenticados de abertura. Não há iproxy separado. No primeiro pareamento exclusivamente por cabo, abra o app manualmente, informe o PIN e toque Conectar; depois o listener usa o PIN salvo.

O .deb instala `/Applications/ShockStream.app`, `/usr/libexec/shockstream-waked` e o registro `com.shock.stream.wake` no launchd. O auxiliar executa como **mobile**, e o estado compartilhado fica em `/var/mobile/Library/Application Support/ShockStream`, com diretório privado e arquivos acessíveis apenas a esse usuário. A remoção do pacote interrompe o auxiliar e remove o aplicativo; o estado de pareamento é preservado para uma reinstalação.

Ao sair pelo Home, o streaming fecha e a abertura USB fica pausada para evitar que o app volte repetidamente. Para retomar, abra o ícone no iPad, use **Retomar iPad USB** no PC ou reconecte o cabo, mantendo a opção de abertura ativada. O auxiliar **não contorna o bloqueio nem a senha do iPad**: desbloqueie-o se o PC solicitar. Pedidos recusados não comprovam que o serviço ou o streaming estejam prontos; consulte **Diagnóstico / copiar** no iPad e a mensagem do PC.

A inicialização do auxiliar após uma reinicialização completa depende do ambiente de jailbreak estar ativo. O pacote não instala nem modifica o jailbreak. A partida automática após reboot e o comportamento ao bloquear/desbloquear precisam ser conferidos no dispositivo físico, mesmo em uma instalação com jailbreak permanente.

Se continuar sem reconhecimento, confira o cabo, Confiar e o Apple Mobile Device Service. O log em %LOCALAPPDATA%/ShockStream/host.log e a mensagem da interface ajudam a distinguir serviço, aparelho e porta do app. Nenhum diagnóstico publica o PIN ou número de série.

## Vídeo e build

H.264 Constrained Baseline por CPU/libx264, sem B-frames, com VideoToolbox no iPad. A captura sobrescreve um único frame bruto. O host espera ACK de decodificação/apresentação antes de codificar o próximo; não descarta pacotes H.264 dependentes nem acumula uma fila de frames atrasados. Áudio de loopback WASAPI, PCM estéreo 44,1 kHz, usa filas limitadas e pode ser desativado.

Wi-Fi autentica desafio HMAC/PIN mas não criptografa a transmissão; use uma rede local de confiança. O serviço não deve ser exposto à internet. Não há encoder GPU, rumble ou catálogo de jogos nesta versão.

O workflow GitHub Actions compila Windows x64, aplicativo iOS 9 ARMv7 e auxiliar nativo. Gera IPA e .deb rootful `iphoneos-arm` com compressão gzip para o instalador legado. Roda testes de protocolo/codec/input/túneis simulados, do protocolo de abertura USB e dos scripts do pacote. Verifica também o executável Windows empacotado, sem instalar drivers ou injetar touch real no runner.

O IPA mantém o bundle ID e CFBundleVersion crescente; o .deb usa versão e build correspondentes. Ambos dependem do ambiente com jailbreak. A verificação lê os arquivos do .deb sem extraí-los, rejeita caminhos indevidos, links e permissões incorretas, confirma o usuário mobile no launchd e confere ARMv7, alvo iOS 9.0 e hashes de código dos dois executáveis. A assinatura ldid não é provisionamento Apple. Drivers oficiais incluídos têm downloads fixados por hash e assinatura verificada no build. Os executáveis próprios do Windows não têm certificado comercial.

O usuário confirmou o streaming Wi-Fi de uma versão anterior. Abertura pelo USB, funcionamento após reboot, bandeja/login, rotação, monitor virtual, recuperação do touch e gamepad desta versão ainda precisam de teste nos equipamentos reais. Build e testes automatizados confirmam as verificações descritas, sem garantir funcionamento em todas as configurações. A latência física não foi medida.

Para desenvolvimento, instale windows/requirements.txt e execute scripts/install_gamepad.py em ambiente isolado. Rode python -m unittest discover -s pc-ipad/tests -v. Dependências e licenças acompanham o pacote em THIRD_PARTY.md e licenses/.
