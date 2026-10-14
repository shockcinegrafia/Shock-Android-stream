# Shock Stream 0.2.0 · Wi-Fi e monitor touch USB

Um programa no Windows 11 x64 gerencia os dois modos. O cliente nativo do iPad mini 1 / iOS 9 ARMv7 usa seu ambiente de jailbreak e instalação pelo Filza.

## Preparação pelo app do PC

Descompacte o pacote Windows, mantendo ShockStream.exe e _internal juntos. Instale o IPA 0.2 no iPad pelo Filza.

Abra ShockStream.exe. Na seção Preparação pelo aplicativo:

- **Instalar gamepad** abre o instalador oficial ViGEmBus incluído. É necessário apenas para o modo Wi-Fi/gamepad.
- **Criar segundo monitor** instala o driver de monitor virtual incluído, com autorização do Windows, e tenta estender a área de trabalho. O helper usa SetupAPI/NewDev para criar somente Root\MttVDD. Não instala drivers em modo de teste nem muda a verificação de assinatura do Windows.
- **Preparar USB Apple** verifica o serviço USB. Se faltar, o Windows Package Manager instala o iTunes/suporte Apple oficial, com o instalador interativo. Precisa de internet nesta primeira preparação. Os binários proprietários da Apple não são redistribuídos dentro do ZIP.
- **Estender área de trabalho** permite solicitar a extensão novamente. **Remover monitor virtual** remove somente o dispositivo Root\MttVDD com autorização do Windows.

A autorização administrativa ocorre apenas quando você aciona um instalador. Os testes e o build não instalam drivers nem mudam monitores no computador. O pacote inclui o driver de tela x64 25.7.23, seu catálogo assinado e o instalador ViGEmBus 1.22.0. Downloads do build têm hashes fixos. As assinaturas dos pacotes são verificadas no GitHub. O helper e o executável próprios não têm certificado comercial.

Se já houver uma configuração C:\VirtualDisplayDriver\vdd_settings.xml, ela é preservada. Em uma instalação nova, o padrão oferece 1024×768 e 768×1024 a 60 Hz, com um monitor. O Windows pode piscar ao instalar/remover um monitor. Não remova o driver enquanto a sessão estiver em uso.

## USB · Monitor touch

1. Conecte o cabo e confirme Confiar neste computador no iPad, se aparecer.
2. No PC, selecione **USB · Monitor touch** e clique **Detectar iPad**. Selecione o aparelho USB.
3. Se quiser uma segunda área de trabalho, use **Criar segundo monitor** e escolha **Monitor virtual** em Tela transmitida. Para espelhar, escolha uma tela física. O app também oferece Atualizar e Estender área de trabalho.
4. Clique **Iniciar**, observe o PIN e, no iPad, escolha **USB · Touch**, informe esse PIN e toque **Aguardar PC pelo USB**. Não precisa informar IP nem usar a mesma rede Wi-Fi.
5. O iPad mostra a tela escolhida, sem gamepad. Toques, arrastes, soltura e cancelamento são enviados à API nativa InjectTouchInput do Windows, com até dez contatos. Os aplicativos do Windows precisam aceitar o tipo de gesto; um sistema anticheat ou aplicativo elevado pode limitar input injetado.

O encaminhamento USB usa diretamente o protocolo Apple usbmux no PC, sem executar um iproxy separado. O app do iPad abre o receptor somente no loopback 127.0.0.1:8091. O suporte Apple do PC lista aparelhos USB, abre esse canal e transporta vídeo/áudio/controles. A porta local do serviço Apple é 27015.

As coordenadas usam a proporção e o retângulo de vídeo efetivamente exibido. Toques iniciados nas barras fora da imagem são ignorados. O host converte para pixels e posição global do monitor selecionado, inclusive em telas à esquerda/acima da principal. Movimentos simultâneos são agrupados em um frame de touch; up usa as mesmas coordenadas do último update, como exige o Windows. Rotação, saída do aplicativo e desconexão cancelam contatos para evitar dedos presos.

Isso é uma tela transmitida por software sobre USB, não uma entrada de vídeo física HDMI. O segundo monitor é criado pelo driver do Windows. Instalação física do driver, pareamento Apple, encaminhamento USB no iOS 9 e comportamento de gestos ainda precisam ser testados com o cabo e o iPad reais.

## Wi-Fi · Gamepad

Coloque os dois na mesma rede. Escolha Wi-Fi no PC, selecione a tela e clique Iniciar. No iPad, escolha Wi-Fi, informe IP e PIN. A porta é 8090; permita a rede privada no Firewall se solicitado. O host não muda o Firewall sozinho.

O gamepad virtual tem dois sticks, direcional, A/B/X/Y, LB/RB, LT/RT, L3/R3, START e BACK. Envia estados completos ao controle Xbox/XInput virtual. O ViGEmBus permanece instalado; não há ADB. Só uma sessão/modo pode estar ativo por vez.

## Vídeo, áudio e limites

H.264 Baseline por CPU/libx264, sem B-frames, resolução máxima padrão de 1024 px e alvo de 30 FPS. A captura mantém apenas o frame bruto mais recente. O host espera a confirmação de decodificação/apresentação antes de codificar outro frame, preservando referências H.264. O iPad usa VideoToolbox e uma camada nativa. Há opções 800/640 px e 20/15 FPS.

Áudio do dispositivo de saída padrão, estéreo PCM 16-bit/44.1 kHz, com filas limitadas. Pode ser desativado. Se falhar, o vídeo continua e o PC mostra a mensagem. Ainda não há encoder por GPU, rumble ou lista de jogos. Conteúdo protegido pode aparecer preto.

Ambos os modos autenticam um desafio HMAC com PIN/nonce. A transmissão não é criptografada: Wi-Fi deve ser uma rede de confiança. Não exponha 8090 à internet. USB usa um canal do serviço local Apple. A latência real não foi medida no iPad físico.

## Build e testes

O workflow Build Shock Stream PC and iPad gera o pacote Windows e o IPA. Windows inclui Python/bibliotecas/driver setup; não executa instaladores no runner. iPad usa Theos/Linux + SDK 9.2, deployment 9.0 e ARMv7. CFBundleVersion cresce com as execuções. A assinatura ldid tem seus hashes de código verificados; depende de instalação compatível com jailbreak, não de provisionamento Apple.

Testes automatizados cobrem H.264, pacotes fragmentados/limites, estado e liberação do gamepad, assinatura, protocolo USB/ordem de bytes, ABI Windows, multitouch, soltura final, cancelamento, agrupamento de movimentos e coordenadas de múltiplos monitores. USB e touch são simulados nos testes: eles não conectam a aparelhos nem injetam eventos reais no desktop.

Para desenvolvimento: instale windows/requirements.txt em ambiente isolado e execute scripts/install_gamepad.py. Depois execute python -m unittest discover -s pc-ipad/tests -v na raiz. O script copia Python/DLL de origem verificada sem executar o instalador do vgamepad.

Log: %LOCALAPPDATA%/ShockStream/host.log. Dependências e licenças: THIRD_PARTY.md.
