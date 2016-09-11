"""Simple Python3 motion detection with picamera on Raspberry Pi"""

import datetime
import io
import logging
import subprocess
import time

import numpy as np
import picamera
import picamera.array
import os


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(name)-12s %(lineno)d %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    # filename='/Users/n8henrie/Dropbox/Launch/n8log.log',
    # filemode='a'
    )

logger_name = "{} :: {}".format(__file__, __name__)
logger = logging.getLogger(logger_name)

class DetectMotion(picamera.array.PiMotionAnalysis):
    def __init__(self, *args, motion_timeout=5, motion_magnitude=30, motion_vector_count=20, **kwargs):
        self.motion_magnitude = motion_magnitude
        self.motion_vector_count = motion_vector_count

        self.motion_detected = False
        self.latest_motion = 0
        self.motion_timeout = motion_timeout

        super().__init__(*args, **kwargs)

    def show_motion_analysis(self, a):
        now = datetime.datetime.now()
        motion_analysis = '\n'.join("{count} greater than {threshold}"
                              .format(count=(a > x).sum(), threshold=x)
                              for x in range(0, 255, 10))
        os.system('clear')
        print("\nMotion analysis at {:%Y-%m-%d-%H%M%S.%f}:\n{}".format(now, motion_analysis))

    def analyze(self, a):
        a = np.sqrt(
            np.square(a['x'].astype(np.float)) +
            np.square(a['y'].astype(np.float))
            ).clip(0, 255).astype(np.uint8)

        ts = time.time()

        # self.show_motion_analysis(a)

        # If more than `motion_vector_count` vector have a magnitude greater
        # than `motion_magnitude`, then motion is detected

        if (a > self.motion_magnitude).sum() > self.motion_vector_count:
            logger.debug("Found motion, resetting latest timestamp")
            self.latest_motion = ts
            self.motion_detected = True
        elif self.motion_detected and (ts - self.latest_motion) > self.motion_timeout:
            logger.debug("No motion for {} seconds, resetting motion detection".format(self.motion_timeout))
            self.motion_detected = False


def write_video(stream, ts):
    # Write the entire content of the circular buffer to disk. No need to
    # lock the stream here as we're definitely not writing to it
    # simultaneously
    logger.debug("Writing video")
    with io.open('{}.h264'.format(ts), 'wb') as output:
        for frame in stream.frames:
            if frame.frame_type == picamera.PiVideoFrameType.sps_header:
                stream.seek(frame.position)
                break
        while True:
            buf = stream.read1()
            if not buf:
                break
            output.write(buf)
    # Wipe the circular stream once we're done
    stream.seek(0)
    stream.truncate()


def concat_vids(ts):
    with open('{}.h264'.format(ts), 'ab') as before, open('after.h264', 'rb') as after:
        before.write(after.read())
    os.remove('after.h264')


def convert_video(ts):
    infile = '{}.h264'.format(ts)
    outfile = '{}.mp4'.format(ts)
    cmd = ['/usr/bin/avconv', '-i', infile, '-acodec', 'copy', '-vcodec', 'copy', outfile]
    result = subprocess.run(cmd, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        os.remove(infile)


def gen_img_name():
    counter = 0
    while True:
        counter += 1
        yield "{:%Y-%m-%d-%H%M%S}-{:03d}.jpg".format(datetime.datetime.now(), counter)


def main(motion_size=(640, 480), flip=False, convert_vids=False, circular_secs=5, still_img_interval=0.25):
    with picamera.PiCamera() as camera:
        if flip:
            camera.rotation = 180
        with picamera.PiCameraCircularIO(camera, seconds=circular_secs) as stream,\
                DetectMotion(camera, size=motion_size) as output:
            camera.start_recording(stream, format='h264')
            camera.start_recording('/dev/null', splitter_port=2, resize=motion_size, format='h264',
                                   motion_output=output)
            img_name = gen_img_name()

            try:
                # Avoid spurious motion detection at startup
                camera.wait_recording(2)
                output.motion_detected = False
                while True:
                    logger.debug("Entering main loop")
                    camera.wait_recording(1)
                    camera.wait_recording(0, splitter_port=2)
                    if output.motion_detected:
                        logger.info("Motion detected, splitting image")
                        camera.split_recording("after.h264")
                        ts = "{:%Y-%m-%d-%H%M%S}".format(datetime.datetime.now())
                        write_video(stream, ts)
                        while output.motion_detected:
                            logger.debug("Waiting for motion to stop")
                            camera.capture(next(img_name), use_video_port=True)
                            camera.wait_recording(still_img_interval)
                        camera.split_recording(stream)
                        concat_vids(ts)

                    # Wiat for period of time with no motion to do video conversion
                    elif convert_vids and (time.time() - output.latest_motion) > convert_vids:
                        convert_video(ts)

            except KeyboardInterrupt:
                pass

            finally:
                logger.debug("Closing recording")
                for sp in [1, 2]:
                    camera.stop_recording(splitter_port=sp)


if __name__ == "__main__":
    main(flip=True, convert_vids=True)
