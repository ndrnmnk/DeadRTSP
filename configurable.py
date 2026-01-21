# EDIT THIS FUNCTION TO CHANGE THE SOURCE
def choose_source(request_text):
    """Gets content source for the stream.
    Returns:
    content_path(str): path to the content; return None if no content
    is_live(bool): True if the stream is live, False otherwise
    """

    return "vids/res.ts", True


def detect_multicast(request_text):
    """Detects multicast addresses from OPTIONS request"""
    return "multicast" in request_text

# EDIT THIS LIST TO INCLUDE YOUR LEGACY DEVICE IF IT DOESN'T WORK AS-IS
legacy_signatures = [
    "helixdnaclient",
    "realmedia player"
    # ADD YOUR DEVICE HERE
]
