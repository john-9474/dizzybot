package io.github.john9474.dizzybot.spotify;

import com.github.topi314.lavasrc.ExtendedAudioPlaylist;
import com.github.topi314.lavasrc.spotify.SpotifyAudioPlaylist;
import com.github.topi314.lavasrc.spotify.SpotifyAudioTrack;
import com.github.topi314.lavasrc.spotify.SpotifySourceManager;
import com.sedmelluq.discord.lavaplayer.tools.JsonBrowser;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.track.AudioTrackInfo;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import org.jsoup.Jsoup;

/** Public web-player metadata only; full audio still comes from LavaSrc's mirror providers. */
final class PublicPlaylistLoader {
  private static final Pattern ID = Pattern.compile("[A-Za-z0-9]{22}");
  private static final int PAGE_SIZE = 100;
  private static final String QUERY_HASH =
      "bb67e0af06e8d6f52b531f97468ee4acd44cd0f82b988e15c2ea47b1148efc77";

  interface Transport {
    String embed(String id) throws IOException;

    JsonBrowser page(String token, String payload) throws IOException;
  }

  private final Transport transport;

  PublicPlaylistLoader(Transport transport) {
    this.transport = transport;
  }

  SpotifyAudioPlaylist load(String id, SpotifySourceManager source, int maxTracks)
      throws IOException {
    if (!ID.matcher(id).matches()) {
      throw new IOException("Invalid Spotify playlist ID.");
    }
    String token = tokenFromEmbed(transport.embed(id));
    List<AudioTrack> tracks = new ArrayList<>();
    String name = null;
    String artwork = null;
    String author = null;
    String revision = null;
    int offset = 0;
    int total = Integer.MAX_VALUE;
    while (offset < total && offset < maxTracks) {
      int limit = Math.min(PAGE_SIZE, maxTracks - offset);
      var response = transport.page(token, payload(id, offset, limit));
      var playlist = response.get("data").get("playlistV2");
      if (!response.get("errors").isNull()
          || playlist.isNull()
          || !"Playlist".equals(playlist.get("__typename").text())
          || !("spotify:playlist:" + id).equals(playlist.get("uri").text())) {
        throw new IOException("Spotify did not return the requested public playlist.");
      }
      var content = playlist.get("content");
      int pageTotal = (int) content.get("totalCount").asLong(-1);
      String pageRevision = playlist.get("revisionId").text();
      if (pageTotal < 0
          || (offset > 0
              && (pageTotal != total || !java.util.Objects.equals(revision, pageRevision)))) {
        throw new IOException("Spotify playlist changed during import; retry the request.");
      }
      total = pageTotal;
      if (offset == 0) {
        revision = pageRevision;
        name = playlist.get("name").text();
        artwork =
            playlist.get("images").get("items").index(0).get("sources").index(0).get("url").text();
        author = playlist.get("ownerV2").get("data").get("name").text();
      }
      var items = content.get("items").values();
      if (items.size() > limit || (items.isEmpty() && offset < total)) {
        throw new IOException("Spotify returned an incomplete public playlist page.");
      }
      for (var item : items) {
        AudioTrack track = track(item.get("itemV2").get("data"), source);
        if (track != null) {
          tracks.add(track);
        }
      }
      offset += items.size();
    }
    if (name == null || name.isBlank()) {
      throw new IOException("Spotify returned a playlist without a title.");
    }
    return new SpotifyAudioPlaylist(
        name,
        tracks,
        ExtendedAudioPlaylist.Type.PLAYLIST,
        "https://open.spotify.com/playlist/" + id,
        artwork,
        author,
        total);
  }

  static String tokenFromEmbed(String html) throws IOException {
    var script = Jsoup.parse(html).getElementById("__NEXT_DATA__");
    if (script == null) {
      throw new IOException("Spotify public playlist session is unavailable.");
    }
    var data = JsonBrowser.parse(script.data());
    String token =
        data.get("props")
            .get("pageProps")
            .get("state")
            .get("settings")
            .get("session")
            .get("accessToken")
            .text();
    if (token == null || token.isBlank()) {
      throw new IOException("Spotify public playlist session is unavailable.");
    }
    return token;
  }

  static String payload(String id, int offset, int limit) {
    return "{\"operationName\":\"fetchPlaylist\",\"variables\":{\"uri\":\"spotify:playlist:"
        + id
        + "\",\"offset\":"
        + offset
        + ",\"limit\":"
        + limit
        + ",\"enableWatchFeedEntrypoint\":false},\"extensions\":{\"persistedQuery\":{"
        + "\"version\":1,\"sha256Hash\":\""
        + QUERY_HASH
        + "\"}}}";
  }

  private static AudioTrack track(JsonBrowser data, SpotifySourceManager source) {
    String uri = data.get("uri").text();
    if (!"Track".equals(data.get("__typename").text())
        || uri == null
        || !uri.startsWith("spotify:track:")) {
      return null;
    }
    String id = uri.substring("spotify:track:".length());
    String title = data.get("name").text();
    long duration = data.get("trackDuration").get("totalMilliseconds").asLong(0);
    List<String> artists =
        data.get("artists").get("items").values().stream()
            .map(artist -> artist.get("profile").get("name").text())
            .filter(artist -> artist != null && !artist.isBlank())
            .toList();
    if (!ID.matcher(id).matches()
        || title == null
        || title.isBlank()
        || duration <= 0
        || artists.isEmpty()) {
      return null;
    }
    String artwork =
        data.get("albumOfTrack").get("coverArt").get("sources").index(0).get("url").text();
    return new SpotifyAudioTrack(
        new AudioTrackInfo(
            title,
            String.join(", ", artists),
            duration,
            id,
            false,
            "https://open.spotify.com/track/" + id,
            artwork,
            null),
        source);
  }
}
