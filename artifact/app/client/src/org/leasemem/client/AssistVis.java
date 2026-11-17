package org.leasemem.client;

import android.content.Intent;
import android.os.Bundle;
import android.service.voice.VoiceInteractionService;
import android.service.voice.VoiceInteractionSession;
import android.service.voice.VoiceInteractionSessionService;
import android.speech.RecognitionService;

/** Minimal default-assistant components, used only by the deployment-model experiment (package org.leasemem.assist).
 *  When this package is the selected voice-interaction service, system_server binds AssistVis, which places the
 *  memory's process in the state an assistant's process would have. */
public class AssistVis extends VoiceInteractionService {
    public static class Session extends VoiceInteractionSessionService {
        @Override public VoiceInteractionSession onNewSession(Bundle args) { return new VoiceInteractionSession(this); }
    }
    public static class Recognizer extends RecognitionService {
        @Override protected void onStartListening(Intent i, Callback cb) {}
        @Override protected void onCancel(Callback cb) {}
        @Override protected void onStopListening(Callback cb) {}
    }
}
