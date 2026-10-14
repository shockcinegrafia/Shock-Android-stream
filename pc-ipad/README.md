# Shock Stream PC → iPad · 0.1.0

Programa para Windows 11 x64 e cliente nativo para iPad mini 1, iOS 9.0+, ARMv7 com jailbreak. Transmite o monitor principal em H.264 e o áudio do PC. O iPad tem gamepad virtual com dois analógicos, A/B/X/Y, direcional, LB/RB, LT/RT, L3/R3, START e BACK. Os comandos chegam ao Windows como controle Xbox 360 virtual.

## Instalação e uso

1. Baixe os dois artefatos do workflow **Build Shock Stream PC and iPad** no GitHub Actions. Descompacte o artefato Windows e depois `ShockStream-Windows-x64.zip`. Mantenha `ShockStream.exe` junto com sua pasta `_internal`.
2. Instale uma vez o [ViGEmBus 1.22.0 do repositório oficial](https://github.com/ViGEm/ViGEmBus/releases/tag/v1.22.0). Se o instalador pedir, reinicie o PC. Não há ADB e não é necessário reativar esse driver a cada partida. O host detecta erro ao criar o controle e orienta a instalação.
3. No iPad com jailbreak e método de instalação de IPA compatível, instale `ShockStream-iOS9-ARMv7.ipa` pelo Filza, como nos outros aplicativos. Este IPA tem assinatura ad hoc; não é provisionado pela Apple para iPads sem jailbreak. AppSync compatível pode ser necessário conforme seu ambiente.
4. Conecte PC e iPad à mesma rede Wi-Fi. Abra `ShockStream.exe`, escolha resolução/FPS e clique **Iniciar transmissão**. Permita acesso à rede privada no Firewall, se o Windows perguntar. O programa não muda o Firewall sozinho.
5. Abra **Shock Stream** no iPad, informe o IPv4 e o PIN de seis dígitos exibidos no PC e toque **Conectar e jogar**. A porta é 8090. Abra o jogo no monitor principal; ele deve aceitar gamepad Xbox/XInput. Se necessário, use o modo janela sem bordas para captura.
6. Use os analógicos e botões na tela. Para encerrar, toque **Desconectar** ou **Parar** no PC. Sair do app desconecta e neutraliza o controle.

O PIN é novo a cada início do host. Para jogar novamente basta abrir os programas. O executável desta primeira versão não tem assinatura comercial. O iPad mantém o último IP, mas não salva o PIN.

## Transmissão e limites

- Captura do monitor principal, com tamanho máximo padrão de 1024 px no maior lado e alvo de 30 FPS. Mantém a proporção; 1920×1080 vira 1024×576. Há opções 800/640 px e 20/15 FPS.
- H.264 Baseline com codificação por CPU/libx264 e sem B-frames. O cliente usa VideoToolbox e apresenta o frame decodificado em uma camada nativa. Ainda não há seleção de encoder por GPU, descoberta automática do PC, lista de jogos ou rumble. Não há garantia de desempenho igual ao Moonlight.
- O capturador sobrescreve um único frame bruto. O host só codifica o próximo após a confirmação de decodificação/apresentação do anterior pelo iPad. Assim descartamos capturas velhas antes de codificar, preservando referências H.264. Existem buffers inevitáveis no codec/sistema; a latência real ainda precisa ser medida no iPad físico.
- Áudio estéreo PCM 16-bit, 44.1 kHz, capturado do dispositivo de saída padrão. A fila do host mantém dois blocos; a do cliente é limitada. Se a captura de áudio falhar, o vídeo continua e o host mostra o motivo. Se houver atraso no Wi-Fi, desative áudio ou reduza resolução/FPS.
- Orientação do iPad altera o layout sem esticar o vídeo. O sistema pode cancelar um toque durante a rotação; o gamepad envia seu novo estado. Suporta botões e ambos os analógicos usados simultaneamente.
- O cliente envia estados completos do gamepad, preserva transições de botões/gatilhos e coalesce movimentos. Uma atualização a cada 250 ms mantém um botão segurado. Após 800 ms sem estado novo o host neutraliza o gamepad; após queda de conexão neutraliza imediatamente.
- O PIN autentica um desafio HMAC com nonce aleatório. A transmissão não é criptografada. Use apenas rede local de confiança; não exponha a porta à internet. Apenas uma sessão é atendida por vez. Jogos com anticheat podem recusar controles virtuais; não há contorno implementado.

## Build e verificações

O código fica em `pc-ipad/windows` e `pc-ipad/ios`, independente do host Android. O workflow Windows usa Python 3.12 e PyInstaller, com bibliotecas empacotadas. Não instala o driver no runner. Os testes cobrem pacotes fragmentados, limites, validação dos eixos, botões/release, watchdog, descarte de capturas, round-trip H.264 e sessão com ACK/control.

O workflow iPad usa a base Theos/Linux + SDK 9.2 adotada no LegacyBrowser. Verifica dentro do IPA a arquitetura ARMv7, deployment target iOS 9, frameworks e assinatura. `CFBundleVersion` cresce com o número de execução do workflow. Isso é verificação de build, não prova de instalação/desempenho no aparelho.

Para testes locais do host: instale `windows/requirements.txt` em um ambiente isolado e execute `python pc-ipad/scripts/install_gamepad.py`, que verifica o arquivo-fonte e copia o módulo/DLL sem rodar instaladores de driver. Execute `python -m unittest discover -s pc-ipad/tests -v` a partir da raiz do repositório. Testes do controle usam um dispositivo simulado e não enviam input ao PC.

## Teste nos aparelhos

Confira som, cores, retrato/paisagem, ambos os sticks + A/B simultâneos, botão mantido por vários segundos, liberação rápida, bloqueio do iPad, desconexão de Wi-Fi e reconexão. Verifique em `joy.cpl` se o Windows vê o controle e se todos os eixos retornam ao centro. Meça atraso com filmagem de alta velocidade antes de atribuir números de latência.

Log do host: `%LOCALAPPDATA%/ShockStream/host.log`. Veja os avisos de dependências em `THIRD_PARTY.md`.
