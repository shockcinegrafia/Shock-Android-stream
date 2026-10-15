# Dependências da versão 0.4.0

Este projeto implementa seu próprio protocolo. Não é um cliente Moonlight nem é compatível com GameStream/Sunshine.

- PyAV 16.1.0: https://github.com/PyAV-Org/PyAV ; o wheel inclui bibliotecas FFmpeg. Código e configuração dos wheels: https://github.com/PyAV-Org/pyav-wheels .
- FFmpeg: https://ffmpeg.org ; libx264: https://www.videolan.org/developers/x264.html . As licenças e a configuração das bibliotecas incluídas devem acompanhar qualquer redistribuição. O pacote inclui os avisos fornecidos pelos wheels instalados; não presume que os binários FFmpeg sejam domínio público.
- MSS 10.1.0: https://github.com/BoboTiG/python-mss .
- NumPy 2.2.6: https://github.com/numpy/numpy .
- SoundCard 0.4.5: https://github.com/bastibe/SoundCard ; CFFI: https://cffi.readthedocs.io .
- vgamepad 0.1.0: https://github.com/yannbouteiller/vgamepad .
- ViGEmBus: https://github.com/ViGEm/ViGEmBus/releases/tag/v1.22.0 . O driver é instalado separadamente pelo usuário. O projeto foi encerrado; esta versão não promete suporte a futuros Windows ou aceitação por todos os sistemas anticheat.
- PyInstaller 6.16.0: https://github.com/pyinstaller/pyinstaller .
- pystray 0.19.5: https://github.com/moses-palmer/pystray/tree/v0.19.5 ; bandeja do Windows, licença LGPL-3.0. Licença da versão: https://github.com/moses-palmer/pystray/blob/v0.19.5/COPYING.LGPL .
- Pillow 12.0.0: https://github.com/python-pillow/Pillow/tree/12.0.0 ; criação do ícone da bandeja, licença MIT-CMU. Licença da versão: https://github.com/python-pillow/Pillow/blob/12.0.0/LICENSE .
- six 1.17.0: https://github.com/benjaminp/six/tree/1.17.0 ; dependência de compatibilidade de pystray, licença MIT. Licença da versão: https://github.com/benjaminp/six/blob/1.17.0/LICENSE .
- Theos: https://github.com/theos/theos ; toolchain ARMv7: https://github.com/L1ghtmann/llvm-project ; SDK legado de build: https://github.com/Sn0wCooder/theos-sdks . SDK e toolchain são usados na compilação e não são incluídos no IPA, .deb ou pacote Windows.

O artefato Windows contém a pasta `licenses/` com licenças encontradas nos pacotes e versões exatas. O build do iPad registra o commit Theos e os hashes dos downloads.

Os pacotes oficiais ViGEmBus 1.22.0 e Virtual Display Driver 25.7.23 são incluídos com hashes fixos, avisos de licença e verificação de assinatura. O código fonte do monitor virtual e licença MIT estão em https://github.com/VirtualDrivers/Virtual-Display-Driver . O helper SetupAPI/NewDev é código próprio e requer autorização do Windows para instalar/remover somente Root\\MttVDD. Não altera a imposição de assinatura de drivers.

O suporte USB proprietário da Apple não é redistribuído: o botão Preparar USB Apple aciona a instalação oficial pelo Windows Package Manager quando falta o serviço. A implementação do protocolo usbmux e a injeção de touch são código próprio baseado nas interfaces documentadas: https://github.com/libimobiledevice/libusbmuxd e https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-injecttouchinput . Instaladores só são iniciados por ação explícita do usuário no app; builds e testes não instalam drivers.

Bonjour no Windows: python-zeroconf 0.151.5 (LGPL-2.1-or-later), https://github.com/python-zeroconf/python-zeroconf ; ifaddr 0.2.0, https://github.com/ifaddr/ifaddr . Os avisos dos pacotes acompanham licenses/. O cliente iOS usa NSNetService/NSNetServiceBrowser do sistema.

O auxiliar USB `shockstream-waked`, o protocolo de abertura autenticada e os scripts do .deb são código próprio. O auxiliar usa Foundation, CoreFoundation e Security do iOS e consulta recursos privados do SpringBoard para solicitar a abertura do app e verificar bloqueio. Esses frameworks pertencem ao sistema Apple e não são redistribuídos pelo projeto. O aplicativo usa também UIKit, AVFoundation, AudioToolbox, VideoToolbox, CoreMedia, CoreVideo e QuartzCore do dispositivo. Essa integração depende do ambiente com jailbreak e não representa uma API pública de abertura automática suportada pela Apple.

O build recolhe avisos de pystray, Pillow e six junto das demais dependências em `licenses/`, com versões exatas em `versions.json`. Ao redistribuir o pacote, mantenha as licenças, avisos e materiais de fontes/build fornecidos; este resumo não substitui os textos das licenças.
