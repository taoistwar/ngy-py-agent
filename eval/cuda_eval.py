import torch

print(torch.__version__)
print(torch.version.cuda)
print("CUDA count:", torch.cuda.device_count())
print(torch.cuda.get_device_name() if torch.cuda.is_available() else "No CUDA GPU")
