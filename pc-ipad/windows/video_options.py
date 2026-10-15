"""Bounded video presets and measured frame/ACK statistics."""
PROFILES={'balanced':2500000,'text':5000000,'economy':1500000}

def bitrate(quality):
    if quality not in PROFILES:raise ValueError('Perfil de vídeo inválido')
    return PROFILES[quality]

class StreamStats:
    def __init__(self,now):self.since=now;self.frames=0;self.bytes=0;self.ack=0;self.encode=0
    def record(self,now,size,ack_seconds,encode_seconds):
        self.frames+=1;self.bytes+=size;self.ack+=ack_seconds;self.encode+=encode_seconds
        elapsed=now-self.since
        if elapsed<2:return None
        result=dict(fps=self.frames/elapsed,mbps=self.bytes*8/elapsed/1000000,
                    ack_ms=self.ack/self.frames*1000,encode_ms=self.encode/self.frames*1000)
        self.__init__(now);return result
