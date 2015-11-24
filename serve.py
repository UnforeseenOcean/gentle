from twisted.web.static import File
from twisted.web.resource import Resource
from twisted.web.server import Site, NOT_DONE_YET
from twisted.internet import reactor

import json
import os
import shutil
import subprocess
import sys
import uuid

from gentle.paths import get_binary, get_resource, get_datadir
from gentle.language_model_transcribe import lm_transcribe, write_csv

DATADIR = get_datadir('webdata')

def _next_id():
    uid = None
    while uid is None or os.path.exists(os.path.join(DATADIR, uid)):
        uid = uuid.uuid4().get_hex()[:8]
    return uid

# The `ffmpeg.to_wav` function doesn't set headers properly for web
# browser playback.
def to_wav(infile, outfile):
    subprocess.call([get_binary('ffmpeg'), '-i', infile,
                     '-ac', '1', '-ar', '8000',
                     '-acodec', 'pcm_s16le',
                     outfile])

class Uploader(Resource):
    def render_POST(self, req):
        uid = _next_id()
        outdir = os.path.join(DATADIR, uid)
        os.makedirs(outdir)

        open(os.path.join(outdir, 'transcript.txt'), 'w').write(
            req.args['transcript'][0])

        data = req.args['audio'][0]
        open(os.path.join(outdir, 'upload'), 'w').write(
            data)

        reactor.callInThread(self.transcribe, uid, req=req)

        req.redirect("/status.html#%s" % (uid))
        req.finish()

        return NOT_DONE_YET

    def transcribe(self, uid, req=None):
        outdir = os.path.join(DATADIR, uid)

        print 'outdir', outdir

        wavfile = os.path.join(outdir, 'a.wav')        
        to_wav(os.path.join(outdir, 'upload'), wavfile)

        print 'wavfile', wavfile

        transcript = open(os.path.join(outdir, 'transcript.txt')).read()

        print 'transcript', transcript

        # Run transcription
        ret = lm_transcribe(wavfile,
                            open(os.path.join(outdir, 'transcript.txt')).read(),
                            # XXX: should be configurable
                            get_resource('PROTO_LANGDIR'),
                            get_resource('data/nnet_a_gpu_online'))

        print 'ret', ret

        # Save output to JSON and CSV
        json.dump({
            "words": ret,
            "transcript": transcript,
        }, open(os.path.join(outdir, 'align.json'), 'w'), indent=2)
        write_csv(ret, open(os.path.join(outdir, 'align.csv'), 'w'))

        # Finally, copy over the HTML
        shutil.copy(get_resource('www/view_alignment.html'), os.path.join(outdir, 'index.html'))

        # ...and remove the original upload
        os.unlink(os.path.join(outdir, 'upload'))

        print 'done with transcription.'

def serve(port=8765, interface='0.0.0.0', installSignalHandlers=0):

    if not os.path.exists(DATADIR):
        os.makedirs(DATADIR)
    
    f = File(DATADIR)

    f.putChild('', File(get_resource('www/index.html')))
    f.putChild('status.html', File(get_resource('www/status.html')))
    
    up = Uploader()

    f.putChild('transcribe', up)
    
    s = Site(f)
    reactor.listenTCP(port, s, interface=interface)
    sys.stderr.write('listening at %s:%d\n' % (interface, port))
    reactor.run(installSignalHandlers=installSignalHandlers)
    
    
if __name__=='__main__':
    interface = '0.0.0.0'
    port = 8765

    serve(port, interface, installSignalHandlers=1)
