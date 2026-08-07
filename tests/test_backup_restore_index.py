from scripts.backup_restore_index import backup, restore


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


def test_backup_copies_existing_files_only(tmp_path):
    index_path = tmp_path / "index.faiss"
    store_path = tmp_path / "prompt_store.pkl"
    metadata_path = tmp_path / "index_metadata.json"
    _write(index_path, "index-bytes")
    _write(store_path, "store-bytes")
    # metadata file intentionally missing

    dest_dir = tmp_path / "backup"
    copied = backup(str(index_path), str(store_path), str(metadata_path), str(dest_dir))

    assert len(copied) == 2
    assert (dest_dir / "index.faiss").read_text() == "index-bytes"
    assert (dest_dir / "prompt_store.pkl").read_text() == "store-bytes"
    assert not (dest_dir / "index_metadata.json").exists()


def test_restore_copies_backup_files_back_into_place(tmp_path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    _write(backup_dir / "index.faiss", "restored-index")
    _write(backup_dir / "prompt_store.pkl", "restored-store")
    _write(backup_dir / "index_metadata.json", '{"bi_encoder_model": "m"}')

    live_dir = tmp_path / "live"
    index_path = live_dir / "index.faiss"
    store_path = live_dir / "prompt_store.pkl"
    metadata_path = live_dir / "index_metadata.json"

    restored = restore(str(index_path), str(store_path), str(metadata_path), str(backup_dir))

    assert len(restored) == 3
    assert index_path.read_text() == "restored-index"
    assert store_path.read_text() == "restored-store"
    assert metadata_path.read_text() == '{"bi_encoder_model": "m"}'


def test_restore_skips_files_missing_from_backup(tmp_path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    _write(backup_dir / "index.faiss", "restored-index")

    live_dir = tmp_path / "live"
    index_path = live_dir / "index.faiss"
    store_path = live_dir / "prompt_store.pkl"
    metadata_path = live_dir / "index_metadata.json"

    restored = restore(str(index_path), str(store_path), str(metadata_path), str(backup_dir))

    assert restored == [str(index_path)]
    assert not store_path.exists()
    assert not metadata_path.exists()


def test_backup_then_restore_round_trip(tmp_path):
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    index_path = live_dir / "index.faiss"
    store_path = live_dir / "prompt_store.pkl"
    metadata_path = live_dir / "index_metadata.json"
    _write(index_path, "abc")
    _write(store_path, "def")
    _write(metadata_path, "ghi")

    backup_dir = tmp_path / "backup"
    backup(str(index_path), str(store_path), str(metadata_path), str(backup_dir))

    _write(index_path, "corrupted")
    _write(store_path, "corrupted")
    _write(metadata_path, "corrupted")

    restore(str(index_path), str(store_path), str(metadata_path), str(backup_dir))

    assert index_path.read_text() == "abc"
    assert store_path.read_text() == "def"
    assert metadata_path.read_text() == "ghi"
