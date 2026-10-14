package io.github.john9474.dizzybot.soundcloud;

import com.sedmelluq.discord.lavaplayer.container.playlists.ExtendedM3uParser;
import java.io.IOException;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;

/** A finite, unencrypted fMP4 media playlist, including the initialization segment. */
record AacPlaylist(URI initialization, List<Segment> segments, long durationMs) {
  record Segment(URI uri, long startMs) {}

  static AacPlaylist parse(URI base, String[] lines) throws IOException {
    URI initialization = null;
    List<Segment> segments = new ArrayList<>();
    boolean ended = false;
    double elapsed = 0;
    double duration = -1;
    for (String text : lines) {
      var line = ExtendedM3uParser.parseLine(text);
      if (line.isDirective()) {
        switch (line.directiveName) {
          case "EXT-X-KEY", "EXT-X-SESSION-KEY" -> {
            if (!"NONE".equals(line.directiveArguments.get("METHOD"))) {
              throw new IOException("Encrypted SoundCloud streams are not supported.");
            }
          }
          case "EXT-X-MAP" -> {
            if (line.directiveArguments.containsKey("BYTERANGE")) {
              throw new IOException("Byte-range initialization is not supported.");
            }
            URI next = resolve(base, line.directiveArguments.get("URI"));
            if (initialization != null && !initialization.equals(next)) {
              throw new IOException(
                  "Changing SoundCloud initialization segments is not supported.");
            }
            initialization = next;
          }
          case "EXT-X-BYTERANGE", "EXT-X-DISCONTINUITY" ->
              throw new IOException(
                  "Unsupported SoundCloud playlist directive: " + line.directiveName);
          case "EXT-X-ENDLIST" -> ended = true;
          case "EXTINF" -> {
            try {
              duration = Double.parseDouble(line.extraData.split(",", 2)[0]);
              if (!Double.isFinite(duration) || duration <= 0) {
                throw new NumberFormatException();
              }
            } catch (NumberFormatException error) {
              throw new IOException("Invalid SoundCloud segment duration.", error);
            }
          }
          default -> {}
        }
      } else if (line.isData()) {
        if (duration < 0 || initialization == null) {
          throw new IOException("Expected a SoundCloud fMP4 media playlist.");
        }
        segments.add(new Segment(resolve(base, line.lineData), Math.round(elapsed * 1000)));
        elapsed += duration;
        duration = -1;
      }
    }
    if (initialization == null || segments.isEmpty() || !ended || duration >= 0) {
      throw new IOException("Incomplete SoundCloud fMP4 media playlist.");
    }
    return new AacPlaylist(initialization, List.copyOf(segments), Math.round(elapsed * 1000));
  }

  private static URI resolve(URI base, String value) throws IOException {
    try {
      if (value == null || value.isBlank()) {
        throw new IllegalArgumentException();
      }
      URI result = base.resolve(value);
      if (!"https".equals(result.getScheme()) || result.getHost() == null) {
        throw new IllegalArgumentException();
      }
      return result;
    } catch (IllegalArgumentException error) {
      throw new IOException("Invalid SoundCloud media URL.", error);
    }
  }

  int segmentAt(long positionMs) {
    if (positionMs >= durationMs) {
      return segments.size();
    }
    for (int i = segments.size() - 1; i >= 0; i--) {
      if (positionMs >= segments.get(i).startMs()) {
        return i;
      }
    }
    return 0;
  }

  boolean sameTimeline(AacPlaylist other) {
    if (segments.size() != other.segments.size() || durationMs != other.durationMs) {
      return false;
    }
    for (int i = 0; i < segments.size(); i++) {
      if (segments.get(i).startMs() != other.segments.get(i).startMs()) {
        return false;
      }
    }
    return true;
  }
}
