package io.github.john9474.dizzybot.spotify;

import com.github.topi314.lavasrc.spotify.SpotifySourceManager;
import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.tools.JsonBrowser;
import com.sedmelluq.discord.lavaplayer.tools.io.HttpClientTools;
import com.sedmelluq.discord.lavaplayer.tools.io.HttpInterfaceManager;
import com.sedmelluq.discord.lavaplayer.track.AudioItem;
import com.sedmelluq.discord.lavaplayer.track.AudioReference;
import dev.arbjerg.lavalink.api.AudioPlayerManagerConfiguration;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;
import org.apache.http.util.EntityUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;

/** Retains native Spotify tracks and mirroring, with a public-playlist fallback for API denials. */
@Service
public final class SpotifySource extends SpotifySourceManager
    implements AudioPlayerManagerConfiguration {
  private static final Logger log = LoggerFactory.getLogger(SpotifySource.class);
  private final AtomicReference<AudioPlayerManager> manager;
  private final HttpInterfaceManager publicHttp =
      HttpClientTools.createCookielessThreadLocalManager();
  private final PublicPlaylistLoader playlists;
  private final boolean enabled;
  private int maxPlaylistTracks = 500;

  @Autowired
  public SpotifySource(
      Environment environment,
      @Value("${plugins.lavasrc.spotify.clientId:}") String clientId,
      @Value("${plugins.lavasrc.spotify.clientSecret:}") String clientSecret,
      @Value("${plugins.lavasrc.spotify.countryCode:GB}") String country) {
    this(providers(environment), clientId, clientSecret, country, new AtomicReference<>());
    setPlaylistPageLimit(
        environment.getProperty("plugins.lavasrc.spotify.playlistLoadLimit", Integer.class, 5));
    setAlbumPageLimit(
        environment.getProperty("plugins.lavasrc.spotify.albumLoadLimit", Integer.class, 10));
    setResolveArtistsInSearch(
        environment.getProperty(
            "plugins.lavasrc.spotify.resolveArtistsInSearch", Boolean.class, false));
    setLocalFiles(
        environment.getProperty("plugins.lavasrc.spotify.localFiles", Boolean.class, false));
  }

  SpotifySource(String[] providers, String clientId, String clientSecret, String country) {
    this(providers, clientId, clientSecret, country, new AtomicReference<>());
  }

  private SpotifySource(
      String[] providers,
      String clientId,
      String clientSecret,
      String country,
      AtomicReference<AudioPlayerManager> manager) {
    super(providers, clientId, clientSecret, country, unused -> manager.get());
    this.manager = manager;
    this.enabled = !clientId.isBlank() && !clientSecret.isBlank();
    this.playlists =
        new PublicPlaylistLoader(
            new PublicPlaylistLoader.Transport() {
              @Override
              public String embed(String id) throws IOException {
                try (var http = publicHttp.getInterface();
                    var response =
                        http.execute(
                            new HttpGet("https://open.spotify.com/embed/playlist/" + id))) {
                  checkStatus(response.getStatusLine().getStatusCode());
                  return EntityUtils.toString(response.getEntity(), StandardCharsets.UTF_8);
                }
              }

              @Override
              public JsonBrowser page(String token, String payload) throws IOException {
                var request = new HttpPost("https://api-partner.spotify.com/pathfinder/v2/query");
                request.setHeader("Authorization", "Bearer " + token);
                request.setHeader("Content-Type", "application/json");
                request.setHeader("app-platform", "WebPlayer");
                request.setEntity(new StringEntity(payload, StandardCharsets.UTF_8));
                try (var http = publicHttp.getInterface();
                    var response = http.execute(request)) {
                  checkStatus(response.getStatusLine().getStatusCode());
                  return JsonBrowser.parse(
                      EntityUtils.toString(response.getEntity(), StandardCharsets.UTF_8));
                }
              }
            });
  }

  private static void checkStatus(int status) throws IOException {
    if (status != 200) {
      throw new IOException("Spotify public playlist request failed (HTTP " + status + ").");
    }
  }

  private static String[] providers(Environment environment) {
    var providers = new ArrayList<String>();
    for (int i = 0; i < 100; i++) {
      String provider = environment.getProperty("plugins.lavasrc.providers[" + i + "]");
      if (provider == null) break;
      providers.add(provider);
    }
    return providers.isEmpty()
        ? new String[] {"ytsearch:\"%ISRC%\"", "ytsearch:%QUERY%", "scsearch:%QUERY%"}
        : providers.toArray(String[]::new);
  }

  @Override
  public AudioPlayerManager configure(AudioPlayerManager playerManager) {
    // Encoded tracks can be restored before the first load request after a restart.
    manager.set(playerManager);
    return playerManager;
  }

  @Override
  public AudioItem loadItem(AudioPlayerManager playerManager, AudioReference reference) {
    if (!enabled) return null;
    manager.compareAndSet(null, playerManager);
    return super.loadItem(playerManager, reference);
  }

  @Override
  public void setPlaylistPageLimit(int pages) {
    super.setPlaylistPageLimit(pages);
    maxPlaylistTracks = Math.max(1, Math.min(pages, 100)) * 100;
  }

  @Override
  public AudioItem getPlaylist(String id, boolean preview) throws IOException {
    try {
      return super.getPlaylist(id, preview);
    } catch (IOException | RuntimeException error) {
      if (preview || !isAccessDenied(error)) throw error;
      log.info("Spotify API denied playlist {}; loading public web-player metadata", id);
      try {
        return loadPublicPlaylist(id);
      } catch (IOException | RuntimeException fallbackError) {
        fallbackError.addSuppressed(error);
        throw fallbackError;
      }
    }
  }

  AudioItem loadPublicPlaylist(String id) throws IOException {
    return playlists.load(id, this, maxPlaylistTracks);
  }

  static boolean isAccessDenied(Throwable error) {
    for (Throwable cause = error; cause != null; cause = cause.getCause()) {
      String message = cause.getMessage();
      if (message != null && message.matches("Response code from channel info is (401|403)")) {
        return true;
      }
    }
    return false;
  }

  @Override
  public void shutdown() {
    super.shutdown();
    try {
      publicHttp.close();
    } catch (IOException error) {
      log.warn("Could not close Spotify public metadata client", error);
    }
  }
}
