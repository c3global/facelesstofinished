from upload_paths import object_id_from_public_file_token


def test_public_file_token_accepts_codec_suffix():
    object_id = "507f1f77bcf86cd799439011"
    assert object_id_from_public_file_token(f"{object_id}.png") == object_id
    assert object_id_from_public_file_token(f"{object_id}.mp4") == object_id


def test_public_file_token_without_suffix_is_unchanged():
    object_id = "507f1f77bcf86cd799439011"
    assert object_id_from_public_file_token(object_id) == object_id
