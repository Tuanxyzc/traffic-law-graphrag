# Corpus Validation Tests

Thư mục này chứa các bài kiểm tra xác thực đồ thị và dữ liệu trên toàn bộ corpus luật (`data/parsed`).

## Đặc điểm

- Các test ở đây yêu cầu dữ liệu đã được parse đầy đủ trong thư mục `data/parsed/`.
- Vì thư mục `data/` được đưa vào `.gitignore` (dung lượng lớn, dữ liệu tải động), các test này được đánh dấu `@pytest.mark.corpus`.
- Trên GitHub Actions CI: Các test này được bỏ qua để CI PR/Push luôn độc lập, nhanh chóng và không phụ thuộc vào data thật.
- Nếu chạy ở môi trường không có `data/parsed/`, test sẽ tự động `SKIP` thay vì báo lỗi đỏ.

## Cách chạy ở Local

Khi đã có dữ liệu `data/parsed`:
```bash
# Chạy riêng kiểm tra corpus
pytest -q tests/corpus

# Hoặc chạy trực tiếp script validation
python tests/corpus/test_full_corpus.py
```
