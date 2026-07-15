# Judge ergonomics — the four things anyone evaluating this repo will do.
.PHONY: mock smoke full report kill test

mock:              ## Verify the entire pipeline offline: $0, no account, <60s
	balagan run --config configs/demo.yaml --mock
	balagan report --config configs/demo.yaml

smoke:             ## 10 trials on Nebius (endpoint + S3 env must be set)
	./nebius/2_run_job.sh "run --config configs/demo.yaml --limit 10"

full:              ## The published sweep (225 trials)
	./nebius/2_run_job.sh

report:            ## Pull trials from Object Storage, build summary + heatmap
	./nebius/3_report.sh configs/full.yaml

kill:              ## The chaos demo: cancel the running job, then `make full` to resume
	@echo "nebius ai job delete <JOB_ID>   # then: make full  → watch the resume line"

test:              ## Regression tests (incl. S3 resume via moto)
	python3 -m pytest tests/ -q
