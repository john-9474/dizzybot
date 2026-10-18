package io.github.john9474.dizzybot.soundcloud;

import com.sedmelluq.discord.lavaplayer.container.mpeg.MpegAacTrackConsumer;
import com.sedmelluq.discord.lavaplayer.container.mpeg.MpegFileLoader;
import com.sedmelluq.discord.lavaplayer.container.mpeg.reader.MpegFileTrackProvider;
import com.sedmelluq.discord.lavaplayer.source.AudioSourceManager;
import com.sedmelluq.discord.lavaplayer.source.soundcloud.SoundCloudHelper;
import com.sedmelluq.discord.lavaplayer.tools.http.HttpStreamTools;
import com.sedmelluq.discord.lavaplayer.tools.io.*;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.track.AudioTrackInfo;
import com.sedmelluq.discord.lavaplayer.track.BaseAudioTrack;
import com.sedmelluq.discord.lavaplayer.track.playback.AudioProcessingContext;
import com.sedmelluq.discord.lavaplayer.track.playback.LocalAudioTrackExecutor;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import org.apache.http.client.methods.HttpGet;

/** Stream SoundCloud fMP4 into the existing AAC decoder; seek by HLS segment. */
final class SoundCloudAacTrack extends BaseAudioTrack {
  private final SoundCloudSource source;

  SoundCloudAacTrack(AudioTrackInfo info, SoundCloudSource source) {
    super(info);
    this.source = source;
  }

  private AacPlaylist loadPlaylist(HttpInterface api, HttpInterface media) throws IOException {
    String lookup = trackInfo.identifier.substring(AacFormatHandler.PREFIX.length());
    URI playback = URI.create(SoundCloudHelper.loadPlaybackUrl(api, lookup));
    return AacPlaylist.parse(
        playback,
        HttpClientTools.fetchResponseLines(
            media, new HttpGet(playback), "SoundCloud AAC playlist"));
  }

  @Override
  public void process(LocalAudioTrackExecutor executor) throws Exception {
    try (HttpInterface api = source.getHttpInterface();
        HttpInterface media = source.getMediaInterface();
        Playback playback = new Playback(api, media, executor.getProcessingContext())) {
      playback.seek(0);
      executor.executeProcessingLoop(
          () -> {
            if (playback.reader != null) {
              playback.reader.provideFrames();
            }
          },
          playback::seek,
          true);
    }
  }

  @Override
  public AudioSourceManager getSourceManager() {
    return source;
  }

  @Override
  protected AudioTrack makeShallowClone() {
    return new SoundCloudAacTrack(trackInfo, source);
  }

  private final class Playback implements AutoCloseable {
    private final HttpInterface http;
    private final AudioProcessingContext context;
    private final RefreshingPlaylist playlists;
    private int segmentIndex;
    private boolean initializationPending;
    private SeekableInputStream stream;
    private MpegAacTrackConsumer consumer;
    private MpegFileTrackProvider reader;

    Playback(HttpInterface api, HttpInterface http, AudioProcessingContext context) {
      this.http = http;
      this.context = context;
      playlists = new RefreshingPlaylist(() -> loadPlaylist(api, http));
    }

    private InputStream nextStream() throws IOException {
      AacPlaylist playlist = playlists.get();
      if (initializationPending) {
        initializationPending = false;
        return HttpStreamTools.streamContent(http, new HttpGet(playlist.initialization()));
      }
      if (segmentIndex >= playlist.segments().size()) {
        return null;
      }
      URI uri = playlist.segments().get(segmentIndex++).uri();
      return HttpStreamTools.streamContent(http, new HttpGet(uri));
    }

    void seek(long positionMs) throws IOException {
      close();
      AacPlaylist playlist = playlists.get();
      segmentIndex = playlist.segmentAt(positionMs);
      if (segmentIndex >= playlist.segments().size()) {
        reader = null;
        return;
      }
      long startMs = playlist.segments().get(segmentIndex).startMs();
      initializationPending = true;
      stream = new NonSeekableInputStream(new ChainedInputStream(this::nextStream));
      MpegFileLoader file = new MpegFileLoader(stream);
      file.parseHeaders();
      var audio =
          file.getTrackList().stream()
              .filter(track -> "soun".equals(track.handler) && "mp4a".equals(track.codecName))
              .findFirst()
              .orElseThrow(
                  () -> new IOException("No AAC track in SoundCloud initialization segment."));
      consumer = new MpegAacTrackConsumer(context, audio);
      consumer.initialise();
      consumer.seekPerformed(positionMs, startMs);
      reader = file.loadReader(consumer);
      if (reader == null) {
        throw new IOException("SoundCloud did not return fragmented MP4 audio.");
      }
    }

    @Override
    public void close() throws IOException {
      try {
        if (consumer != null) {
          consumer.close();
          consumer = null;
        }
      } finally {
        if (stream != null) {
          stream.close();
          stream = null;
        }
      }
    }
  }
}
