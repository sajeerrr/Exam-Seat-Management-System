from django.test import TestCase
from .models import UploadedFile


class UploadedFileModelTests(TestCase):
    def test_default_status_is_uploaded(self):
        upload = UploadedFile.objects.create(
            file="uploads/test/sample.pdf",
            original_filename="sample.pdf",
            file_kind=UploadedFile.FileKind.STUDENT_LIST,
            source_format=UploadedFile.SourceFormat.PDF,
        )
        self.assertEqual(upload.status, UploadedFile.Status.UPLOADED)
        self.assertIsNone(upload.processed_at)

    def test_str_representation(self):
        upload = UploadedFile.objects.create(
            file="uploads/test/sample.pdf",
            original_filename="sample.pdf",
            file_kind=UploadedFile.FileKind.CLASSROOM_LIST,
            source_format=UploadedFile.SourceFormat.XLSX,
        )
        self.assertEqual(str(upload), "sample.pdf (Uploaded)")
