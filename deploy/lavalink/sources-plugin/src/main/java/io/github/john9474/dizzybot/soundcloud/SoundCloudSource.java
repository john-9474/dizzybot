package io.github.john9474.dizzybot.soundcloud;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.source.soundcloud.*;
import com.sedmelluq.discord.lavaplayer.tools.io.HttpClientTools;
import com.sedmelluq.discord.lavaplayer.tools.io.HttpInterface;
import com.sedmelluq.discord.lavaplayer.tools.io.HttpInterfaceManager;
import com.sedmelluq.discord.lavaplayer.track.*;
import java.io.DataInput;
import java.io.IOException;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/** Use the public Lavalink source-plugin API and LavaPlayer's existing SoundCloud loaders. */
@Service
public final class SoundCloudSource extends SoundCloudAudioSourceManager {
  // The upstream API filter adds client_id to requests. Signed URLs on the new
  // soundcloud.cloud CDN must be fetched verbatim or the signature is rejected.
  private final HttpInterfaceManager media = HttpClientTools.createCookielessThreadLocalManager();

  @Autowired
  public SoundCloudSource(
      @Value("${lavalink.server.soundcloudSearchEnabled:true}") boolean allowSearch,
      @Value("${lavalink.server.soundcloudFilterOutPreviewTracks:true}") boolean filterPreviews) {
    this(
        allowSearch,
        filterPreviews,
        new DefaultSoundCloudDataReader(),
        new DefaultSoundCloudDataLoader(),
        new AacFormatHandler());
  }

  private SoundCloudSource(
      boolean allowSearch,
      boolean filterPreviews,
      SoundCloudDataReader reader,
      SoundCloudDataLoader loader,
      SoundCloudFormatHandler formats) {
    super(
        allowSearch,
        reader,
        loader,
        formats,
        new DefaultSoundCloudPlaylistLoader(loader, reader, formats),
        filterPreviews);
  }

  private AudioTrack adapt(AudioTrack track) {
    return track.getIdentifier().startsWith(AacFormatHandler.PREFIX)
        ? new SoundCloudAacTrack(track.getInfo(), this)
        : track;
  }

  @Override
  public AudioItem loadItem(AudioPlayerManager manager, AudioReference reference) {
    return adaptItem(super.loadItem(manager, reference));
  }

  AudioItem adaptItem(AudioItem item) {
    if (item instanceof AudioTrack track) {
      return adapt(track);
    }
    if (item instanceof AudioPlaylist playlist) {
      List<AudioTrack> tracks = playlist.getTracks().stream().map(this::adapt).toList();
      AudioTrack selectedTrack = playlist.getSelectedTrack();
      int selected = selectedTrack == null ? -1 : playlist.getTracks().indexOf(selectedTrack);
      return new BasicAudioPlaylist(
          playlist.getName(),
          tracks,
          selected < 0 ? null : tracks.get(selected),
          playlist.isSearchResult());
    }
    return item;
  }

  @Override
  public AudioTrack decodeTrack(AudioTrackInfo info, DataInput input) {
    return adapt(super.decodeTrack(info, input));
  }

  HttpInterface getMediaInterface() {
    return media.getInterface();
  }

  @Override
  public void shutdown() {
    super.shutdown();
    try {
      media.close();
    } catch (IOException error) {
      throw new IllegalStateException("Could not close SoundCloud media client.", error);
    }
  }
}
