# Dependências da versão 0.1

Este projeto implementa seu próprio protocolo. Não é um cliente Moonlight nem é compatível com GameStream/Sunshine.

- PyAV 16.1.0: https://github.com/PyAV-Org/PyAV ; o wheel inclui bibliotecas FFmpeg. Código e configuração dos wheels: https://github.com/PyAV-Org/pyav-wheels .
- FFmpeg: https://ffmpeg.org ; libx264: https://www.videolan.org/developers/x264.html . As licenças e a configuração das bibliotecas incluídas devem acompanhar qualquer redistribuição. O pacote inclui os avisos fornecidos pelos wheels instalados; não presume que os binários FFmpeg sejam domínio público.
- MSS 10.1.0: https://github.com/BoboTiG/python-mss .
- NumPy 2.2.6: https://github.com/numpy/numpy .
- SoundCard 0.4.5: https://github.com/bastibe/SoundCard ; CFFI: https://cffi.readthedocs.io .
- vgamepad 0.1.0: https://github.com/yannbouteiller/vgamepad .
- ViGEmBus: https://github.com/ViGEm/ViGEmBus/releases/tag/v1.22.0 . O driver é instalado separadamente pelo usuário. O projeto foi encerrado; esta versão não promete suporte a futuros Windows ou aceitação por todos os sistemas anticheat.
- PyInstaller 6.16.0: https://github.com/pyinstaller/pyinstaller .
- Theos: https://github.com/theos/theos ; toolchain ARMv7: https://github.com/L1ghtmann/llvm-project ; SDK legado de build: https://github.com/Sn0wCooder/theos-sdks . SDK e toolchain não são distribuídos no IPA nem no pacote Windows.

O artefato Windows contém a pasta `licenses/` com licenças encontradas nos pacotes e versões exatas. O build do iPad registra o commit Theos e os hashes dos downloads. O programa não baixa nem instala drivers automaticamente.
