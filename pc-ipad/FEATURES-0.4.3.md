# Windows 0.4.3 — cursor, monitor principal e ajustes durante a sessão

Esta atualização funciona com o app iPad 0.4.2 já instalado. Não altera o protocolo, as portas, o pareamento, o auxiliar USB, os drivers ou o cliente iOS. Implementa recursos próprios de uso como monitor, semelhantes aos desejados no estudo do spacedesk, sem copiar seus binários.

## Ponteiro do mouse

A implementação Windows da biblioteca MSS 10.1.0 retorna None em `_cursor_impl()`. Por isso o vídeo mostrava a área de trabalho, mas não o ponteiro do mouse. `cursor_capture.py` agora usa GetCursorInfo, uma cópia do cursor e DrawIconEx para desenhar o formato nativo sobre um pequeno recorte BGRA antes da compressão H.264. Respeita hotspot, transparência/máscaras, bordas e posições negativas de monitores. Os bitmaps, ícones copiados e DCs são liberados.

A opção **Mostrar ponteiro do mouse na transmissão** vem ativada e pode ser alterada sem reconectar. O ponteiro aparece quando o mouse está sobre a tela transmitida e o Windows o considera visível. Ele não é forçado em aplicativos que o escondem nem durante a supressão normal por touch. A opção não move o mouse nem muda o cursor do sistema. Uma falha de desenho não encerra o vídeo e é tentada novamente depois.

Referências: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getcursorinfo , https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-drawiconex , https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection .

## Alternar entre monitor principal e virtual

Em **Tela transmitida**, selecione **Monitor principal** para ver e controlar o desktop principal do PC, ou **Monitor virtual** para usar a área independente. A seleção agora atualiza a sessão existente em vez de fechar o socket e reiniciar o host. Também é possível atualizar a lista de telas enquanto transmite e ativar a extensão de um monitor virtual que já está instalado.

Cada mudança neutraliza o input, invalida capturas antigas e reinicia o encoder com os parâmetros da nova imagem. O retângulo de touch acompanha a tela selecionada. O input só é reativado após o ACK do primeiro frame da geometria atual. Nenhum comando é usado para tornar a tela principal virtual ou mudar sua resolução: uma fonte física mantém a proporção e pode deixar barras no iPad.

Mudanças de resolução/posição feitas nas configurações do Windows são detectadas. Se o DC de captura ficar temporariamente inválido, ele é recriado com tentativas por até três segundos. Nesse intervalo pode haver congelamento breve, com o input suspenso. Se a tela selecionada desaparecer e houver outro monitor, o programa continua no principal e avisa no PC. Falhas persistentes, perda de cabo/rede e instalação/remoção de drivers ainda podem interromper uma sessão. Trocar transporte ou modo touch/gamepad continua sendo uma mudança separada que reinicia a espera por conexão.

## Perfis e indicadores

- **Equilibrado**: mantém o padrão anterior, alvo de 2,5 Mb/s.
- **Texto mais nítido**: alvo de 5 Mb/s para reduzir perdas de compressão, com maior consumo de rede.
- **Economizar rede**: alvo de 1,5 Mb/s.

Perfil, FPS e limite de resolução podem ser alterados durante a sessão. São alvos de codificação, não garantias de bitrate ou de qualidade perceptual. Permanecem H.264 Baseline, sem B-frames, captura com um slot e espera pelo ACK. O perfil escolhido é salvo; o padrão inicial continua equilibrado.

O indicador no PC mostra FPS de frames entregues/confirmados, taxa de vídeo e tempo entre envio do frame e seu ACK. Essa resposta inclui envio, processamento no iPad e retorno da confirmação; não mede sozinha latência física ponta a ponta. Os números são medidos no fluxo atual, não estimativas fixas.

## Validação

135 testes Python terminaram sem falhas nesta máquina, com 7 checks POSIX/Linux ignorados no Windows. Os testes novos verificam desenho nativo do cursor em memória sem mover o mouse, recorte em bordas, perfis H.264, cálculo dos indicadores, recuperação de falha de captura e mudança de posição/resolução. Um teste completo alterna virtual → principal → virtual e muda o perfil pela mesma conexão TCP; verifica o decoder e o bloqueio do touch até o ACK.

O self-test da versão fonte e do executável empacotado também desenha um cursor nativo em memória. CI continua validando os clientes legados e os pacotes. A verificação não instala drivers, não muda monitores reais e não injeta input na área de trabalho do usuário. O funcionamento no iPad físico ainda precisa ser conferido após a atualização Windows.
