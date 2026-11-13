# Rendered by `make cluster` (the model folder must be an absolute path).
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraMounts:
      - hostPath: ${MODELS_DIR}     # local/models on the Mac
        containerPath: /models
        readOnly: true
    extraPortMappings:
      - containerPort: 30080        # assistant NodePort
        hostPort: 8080
