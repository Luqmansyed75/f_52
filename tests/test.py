from transformers import AutoProcessor

processor = AutoProcessor.from_pretrained("Qwen/Qwen3-ASR-1.7B-hf")

print(processor.apply_transcription_request.__doc__)