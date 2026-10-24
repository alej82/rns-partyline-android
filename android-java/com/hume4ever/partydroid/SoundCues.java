package com.hume4ever.partydroid;

import android.media.AudioAttributes;
import android.media.SoundPool;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;

/**
 * Low-latency local sound cues. All pool work is serialized on the Android
 * main Looper so Python may call from the Kivy thread or the engine thread,
 * including while the Kivy UI loop is paused in the background.
 */
public final class SoundCues {
    private static final String TAG = "PARTYLINE_SOUND";
    private static final int MAX_STREAMS = 3;
    private static final Object LOCK = new Object();

    private static Handler handler;
    private static SoundPool messagePool;
    private static SoundPool pttPool;
    private static int messageId;
    private static int pttStartId;
    private static int pttStopId;
    private static boolean messageReady;
    private static boolean pttStartReady;
    private static boolean pttStopReady;
    private static boolean initialized;

    private SoundCues() {
    }

    public static void initialize(final String directory) {
        synchronized (LOCK) {
            if (initialized) {
                return;
            }
            if (handler == null) {
                handler = new Handler(Looper.getMainLooper());
            }
            final Handler mainHandler = handler;
            mainHandler.post(new Runnable() {
                @Override
                public void run() {
                    initializeOnMain(directory);
                }
            });
        }
    }

    private static void initializeOnMain(String directory) {
        synchronized (LOCK) {
            if (initialized) {
                return;
            }
            initialized = true;
            messageReady = false;
            pttStartReady = false;
            pttStopReady = false;

            try {
                AudioAttributes messageAttributes = new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build();
                AudioAttributes pttAttributes = new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION_SIGNALLING)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build();

                messagePool = new SoundPool.Builder()
                        .setMaxStreams(MAX_STREAMS)
                        .setAudioAttributes(messageAttributes)
                        .build();
                pttPool = new SoundPool.Builder()
                        .setMaxStreams(2)
                        .setAudioAttributes(pttAttributes)
                        .build();

                messagePool.setOnLoadCompleteListener(
                        new SoundPool.OnLoadCompleteListener() {
                            @Override
                            public void onLoadComplete(SoundPool pool, int sampleId, int status) {
                                if (status != 0) {
                                    Log.e(TAG, "message cue load failed sampleId=" + sampleId
                                            + " status=" + status);
                                    return;
                                }
                                if (sampleId == messageId) {
                                    messageReady = true;
                                    Log.i(TAG, "cue ready label=message sampleId=" + sampleId);
                                }
                            }
                        });
                pttPool.setOnLoadCompleteListener(
                        new SoundPool.OnLoadCompleteListener() {
                            @Override
                            public void onLoadComplete(SoundPool pool, int sampleId, int status) {
                                if (status != 0) {
                                    Log.e(TAG, "PTT cue load failed sampleId=" + sampleId
                                            + " status=" + status);
                                    return;
                                }
                                if (sampleId == pttStartId) {
                                    pttStartReady = true;
                                    Log.i(TAG, "cue ready label=ptt_start sampleId=" + sampleId);
                                } else if (sampleId == pttStopId) {
                                    pttStopReady = true;
                                    Log.i(TAG, "cue ready label=ptt_stop sampleId=" + sampleId);
                                }
                            }
                        });

                messageId = load(messagePool, directory, "message.wav", "message");
                pttStartId = load(pttPool, directory, "ptt_start.wav", "ptt_start");
                pttStopId = load(pttPool, directory, "ptt_stop.wav", "ptt_stop");
                Log.i(TAG, "initialized directory=" + directory);
            } catch (Exception error) {
                Log.e(TAG, "could not initialize cue pools", error);
                releasePools();
                initialized = false;
            }
        }
    }

    private static int load(SoundPool pool, String directory, String name, String label) {
        File file = new File(directory, name);
        if (!file.isFile()) {
            Log.e(TAG, "missing cue asset label=" + label + " path=" + file.getAbsolutePath());
            return 0;
        }
        try {
            int id = pool.load(file.getAbsolutePath(), 1);
            Log.i(TAG, "loading cue label=" + label + " id=" + id);
            return id;
        } catch (Exception error) {
            Log.e(TAG, "could not load cue label=" + label, error);
            return 0;
        }
    }

    public static void playMessage() {
        play(messagePool, messageId, messageReady, "message");
    }

    public static void playPttStart() {
        play(pttPool, pttStartId, pttStartReady, "ptt_start");
    }

    public static void playPttStop() {
        play(pttPool, pttStopId, pttStopReady, "ptt_stop");
    }

    private static void play(
            final SoundPool pool,
            final int sampleId,
            final boolean ready,
            final String label) {
        final Handler mainHandler;
        synchronized (LOCK) {
            mainHandler = handler;
        }
        if (mainHandler == null) {
            Log.w(TAG, "play ignored before initialization label=" + label);
            return;
        }
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                synchronized (LOCK) {
                    if (!initialized) {
                        Log.w(TAG, "play ignored after release label=" + label);
                        return;
                    }
                }
                if (pool == null || sampleId == 0 || !ready) {
                    Log.w(TAG, "play ignored, cue not ready label=" + label);
                    return;
                }
                try {
                    int streamId = pool.play(sampleId, 1.0f, 1.0f, 1, 0, 1.0f);
                    if (streamId > 0) {
                        Log.i(TAG, "played label=" + label + " stream=" + streamId);
                    } else {
                        Log.w(TAG, "play returned no stream label=" + label);
                    }
                } catch (Exception error) {
                    Log.e(TAG, "playback failed label=" + label, error);
                }
            }
        });
    }

    public static void release() {
        final Handler mainHandler;
        synchronized (LOCK) {
            mainHandler = handler;
        }
        if (mainHandler == null) {
            releasePools();
            return;
        }
        mainHandler.removeCallbacksAndMessages(null);
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                releasePools();
                synchronized (LOCK) {
                    if (handler == mainHandler) {
                        handler = null;
                    }
                    initialized = false;
                }
            }
        });
    }

    private static void releasePools() {
        if (messagePool != null) {
            messagePool.release();
            messagePool = null;
        }
        if (pttPool != null) {
            pttPool.release();
            pttPool = null;
        }
        messageId = 0;
        pttStartId = 0;
        pttStopId = 0;
        messageReady = false;
        pttStartReady = false;
        pttStopReady = false;
    }
}
