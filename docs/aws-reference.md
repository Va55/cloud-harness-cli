# AWS Reference for Management Harness

> **Updated:** 2025 | **Source:** boto3 docs, AWS CLI 2.40.2, AWS Products page
> **Infrastructure:** 39 Regions, 124 Availability Zones, plans for 7 more AZs + 2 new regions

---

## Table of Contents
1. [Core Identity & Access](#1-core-identity--access)
2. [Compute](#2-compute)
3. [Networking & CDN](#3-networking--cdn)
4. [Storage](#4-storage)
5. [Databases](#5-databases)
6. [Analytics & AI/ML](#6-analytics--aiml)
7. [Serverless & Application Integration](#7-serverless--application-integration)
8. [Management & Governance](#8-management--governance)
9. [Security, Identity & Compliance](#9-security-identity--compliance)
10. [Monitoring & Observability](#10-monitoring--observability)
11. [Developer Tools](#11-developer-tools)
12. [Migration & Transfer](#12-migration--transfer)
13. [IoT & Edge](#13-iot--edge)
14. [Business Applications](#14-business-applications)
15. [Financial Operations](#15-financial-operations)
16. [Specialty / Vertical Services](#16-specialty--vertical-services)
17. [Multi-Language SDK Mapping](#17-multi-language-sdk-mapping)
18. [AWS CLI Quick Reference](#18-aws-cli-quick-reference)

---

## 1. Core Identity & Access

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| IAM | `boto3.client('iam')` | `aws iam` | Users, roles, policies, access keys |
| STS | `boto3.client('sts')` | `aws sts` | Temporary credentials, federation, role assumption |
| SSO | `boto3.client('sso')` | `aws sso` | Single sign-on user portal |
| SSO Admin | `boto3.client('sso-admin')` | `aws sso-admin` | SSO tenant management, permission sets |
| SSO OIDC | `boto3.client('sso-oidc')` | `aws sso-oidc` | OIDC device authorization |
| Organizations | `boto3.client('organizations')` | `aws organizations` | Multi-account management, SCPs |
| Access Analyzer | `boto3.client('accessanalyzer')` | `aws accessanalyzer` | Resource sharing analysis |
| IAM Roles Anywhere | `boto3.client('rolesanywhere')` | `aws rolesanywhere` | Cert-based auth for on-prem/edge |
| IAM Toolbox | `boto3.client('iam-toolbox')` | `aws iam-toolbox` | IAM policy auditing |
| Identity Store | `boto3.client('identitystore')` | `aws identitystore` | Directory user/group management |
| Cognito Identity | `boto3.client('cognito-identity')` | `aws cognito-identity` | Federated identity pools |
| Cognito IDP | `boto3.client('cognito-idp')` | `aws cognito-idp` | User pools (auth N/A) |
| Cognito Sync | `boto3.client('cognito-sync')` | `aws cognito-sync` | Data sync across devices |
| Verified Permissions | `boto3.client('verifiedpermissions')` | `aws verifiedpermissions` | Custom authorization |
| KMS | `boto3.client('kms')` | `aws kms` | Key management, encryption |
| Secrets Manager | `boto3.client('secretsmanager')` | `aws secretsmanager` | Secret rotation/storage |

## 2. Compute

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| EC2 | `boto3.client('ec2')` | `aws ec2` | Virtual servers, networking, storage |
| EC2 Instance Connect | `boto3.client('ec2-instance-connect')` | `aws ec2-instance-connect` | SSH key push to EC2 |
| EBS | `boto3.client('ebs')` | `aws ebs` | EBS direct APIs |
| Auto Scaling | `boto3.client('autoscaling')` | `aws autoscaling` | Scale groups |
| Auto Scaling Plans | `boto3.client('autoscaling-plans')` | `aws autoscaling-plans` | Scaling plan mgmt |
| Application Auto Scaling | `boto3.client('application-autoscaling')` | `aws application-autoscaling` | Custom resource scaling |
| EC2 Image Builder | `boto3.client('imagebuilder')` | `aws imagebuilder` | AMI/OVF build automation |
| EC2 Launch Wizard | `boto3.client('launch-wizard')` | `aws launch-wizard` | Deploy scalable apps |
| Elastic Beanstalk | `boto3.client('elasticbeanstalk')` | `aws elasticbeanstalk` | Platform-as-a-Service |
| ECS | `boto3.client('ecs')` | `aws ecs` | Container orchestration (Docker) |
| EKS | `boto3.client('eks')` | `aws eks` | Kubernetes orchestration |
| EKS Auth | `boto3.client('eks-auth')` | `aws eks-auth` | K8s auth API |
| ECR | `boto3.client('ecr')` | `aws ecr` | Container registry |
| ECR Public | `boto3.client('ecr-public')` | `aws ecr-public` | Public container images |
| Fargate | Part of ECS/EKS | — | Serverless containers |
| Batch | `boto3.client('batch')` | `aws batch` | Batch computing workloads |
| Lightsail | `boto3.client('lightsail')` | `aws lightsail` | VPS + simple stack |
| Outposts | `boto3.client('outposts')` | `aws outposts` | Dedicated on-prem racks |
| Snow Family | `boto3.client('snow-device-management')` | `aws snow-device-management` | Edge compute/transfer |
| Snowball | `boto3.client('snowball')` | `aws snowball` | Petabyte-scale transfer |
| App Runner | `boto3.client('apprunner')` | `aws apprunner` | Container web apps (serverless) |
| AppStream 2.0 | `boto3.client('appstream')` | `aws appstream` | Desktop apps streaming |
| Elemental MediaConvert | `boto3.client('mediaconvert')` | `aws mediaconvert` | Video transcode |
| Parallel Computing | `boto3.client('pcs')` | `aws pcs` | Slurm HPC clusters |

## 3. Networking & CDN

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| VPC Lattice | `boto3.client('vpc-lattice')` | `aws vpc-lattice` | Service mesh on VPC |
| Direct Connect | `boto3.client('directconnect')` | `aws directconnect` | Dedicated network links |
| Global Accelerator | `boto3.client('globalaccelerator')` | `aws globalaccelerator` | Anycast static IPs |
| API Gateway | `boto3.client('apigateway')` | `aws apigateway` | REST/WebSocket APIs |
| API Gateway v2 | `boto3.client('apigatewayv2')` | `aws apigatewayv2` | HTTP/WebSocket APIs |
| API Gateway Mgmt API | `boto3.client('apigatewaymanagementapi')` | `aws apigatewaymanagementapi` | WebSocket mgmt |
| CloudFront | `boto3.client('cloudfront')` | `aws cloudfront` | CDN |
| CloudFront KeyValueStore | `boto3.client('cloudfront-keyvaluestore')` | `aws cloudfront-keyvaluestore` | Edge key-value store |
| Route 53 | `boto3.client('route53')` | `aws route53` | DNS + health checks |
| Route 53 Domains | `boto3.client('route53domains')` | `aws route53domains` | Domain registration |
| Route 53 Global Resolver | `boto3.client('route53globalresolver')` | `aws route53globalresolver` | Hybrid DNS routing |
| Route 53 Profiles | `boto3.client('route53profiles')` | `aws route53profiles` | Route 53 config bundles |
| Route 53 Resolver | `boto3.client('route53resolver')` | `aws route53resolver` | Inbound/Outbound DNS |
| Network Manager | `boto3.client('networkmanager')` | `aws networkmanager` | Global network mgmt |
| Transit Gateway | Part of EC2 | — | Hub-spoke networking |
| App Mesh | `boto3.client('appmesh')` | `aws appmesh` | Service mesh |
| Network Firewall | `boto3.client('network-firewall')` | `aws network-firewall` | Managed firewall |
| Network Security Manager | `boto3.client('network-security-manager')` | `aws network-security-manager` | NSM customer API |
| Private CA | `boto3.client('acm-pca')` | `aws acm-pca` | Private certificate authority |
| ACM | `boto3.client('acm')` | `aws acm` | Public cert mgmt |
| PCA Connector AD | `boto3.client('pca-connector-ad')` | `aws pca-connector-ad` | PKI + AD |
| PCA Connector SCEP | `boto3.client('pca-connector-scep')` | `aws pca-connector-scep` | SCEP protocol support |

## 4. Storage

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| S3 | `boto3.client('s3')` | `aws s3` | Object storage (sync) |
| S3 API | `boto3.client('s3')` | `aws s3api` | Object operations |
| S3 Control | `boto3.client('s3control')` | `aws s3control` | Account-level config |
| S3 Tables | `boto3.client('s3tables')` | `aws s3tables` | Tabular data on S3 |
| S3 Vectors | `boto3.client('s3vectors')` | `aws s3vectors` | Vector embeddings storage |
| S3 Files | `boto3.client('s3files')` | `aws s3files` | File system on S3 |
| S3 Outposts | `boto3.client('s3outposts')` | `aws s3outposts` | S3 on Outposts |
| EFS | `boto3.client('efs')` | `aws efs` | Elastic file system |
| FSx | `boto3.client('fsx')` | `aws fsx` | File systems (Windows/Lustre/Octfs/ONTAP) |
| Glacier | `boto3.client('glacier')` | `aws glacier` | Archive storage |
| Storage Gateway | `boto3.client('storagegateway')` | `aws storagegateway` | On-prem ↔ cloud bridge |
| DataSync | `boto3.client('datasync')` | `aws datasync` | Automated data transfer |
| Transfer Family | `boto3.client('transfer')` | `aws transfer` | SFTP/FTPS/FTP over VPC |
| EBS | `boto3.client('ebs')` | `aws ebs` | Block storage snapshots |
| Recycle Bin | `boto3.client('rbin')` | `aws rbin` | S3 object protection |

## 5. Databases

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| RDS | `boto3.client('rds')` | `aws rds` | MySQL, PostgreSQL, Oracle, SQL Server, MariaDB |
| RDS Data API | `boto3.client('rds-data')` | `aws rds-data` | Serverless data API (Aurora) |
| Aurora DSQL | `boto3.client('dsql')` | `aws dsql` | Distributed SQL |
| DynamoDB | `boto3.client('dynamodb')` | `aws dynamodb` | NoSQL key-value/document |
| DynamoDB Streams | `boto3.client('dynamodbstreams')` | `aws dynamodbstreams` | Stream records |
| DocumentDB | `boto3.client('docdb')` | `aws docdb` | MongoDB-compatible |
| DocumentDB Elastic | `boto3.client('docdb-elastic')` | `aws docdb-elastic` | Serverless DocumentDB |
| ElastiCache | `boto3.client('elasticache')` | `aws elasticache` | Redis/Memcached |
| Keyspaces | `boto3.client('keyspaces')` | `aws keyspaces` | Apache Cassandra-compatible |
| Keyspaces Streams | `boto3.client('keyspacesstreams')` | `aws keyspacesstreams` | Cassandra stream records |
| Neptune | `boto3.client('neptune')` | `aws neptune` | Graph database |
| Neptune Graph | `boto3.client('neptune-graph')` | `aws neptune-graph` | Managed graph queries |
| Neptune Data | `boto3.client('neptunedata')` | `aws neptunedata` | Neptune interactive queries |
| Timestream | `boto3.client('timestream-write')` | `aws timestream-write` | Time-series DB write |
| Timestream Query | `boto3.client('timestream-query')` | `aws timestream-query` | Time-series DB query |
| Timestream InfluxDB | `boto3.client('timestream-influxdb')` | `aws timestream-influxdb` | Managed InfluxDB |
| Redshift | `boto3.client('redshift')` | `aws redshift` | Data warehouse |
| Redshift Data API | `boto3.client('redshift-data')` | `aws redshift-data` | Serverless Redshift queries |
| Redshift Serverless | `boto3.client('redshift-serverless')` | `aws redshift-serverless` | Serverless warehouse |
| MemoryDB | `boto3.client('memorydb')` | `aws memorydb` | In-memory DB (Redis-compatible) |
| DAX | `boto3.client('dax')` | `aws dax` | DynamoDB cache |
| Aurora DSQL | `boto3.client('dsql')` | `aws dsql` | Distributed SQL engine |
| AmazonMQ | `boto3.client('mq')` | `aws mq` | Managed Apache MQ (broker) |
| OpenSearch | `boto3.client('opensearch')` | `aws opensearch` | Elasticsearch-compatible |
| OpenSearch Serverless | `boto3.client('opensearchserverless')` | `aws opensearchserverless` | Serverless search/analytics |
| Elasticsearch Service | `boto3.client('es')` | `aws es` | Legacy OpenSearch/ES |
| Aurora Serverless v2 | Part of RDS | — | Auto-scaling PostgreSQL/MySQL |

## 6. Analytics & AI/ML

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| Athena | `boto3.client('athena')` | `aws athena` | Serverless SQL on S3 |
| Glue | `boto3.client('glue')` | `aws glue` | ETL, data catalog |
| Glue DataBrew | `boto3.client('databrew')` | `aws databrew` | Visual data prep |
| EMR | `boto3.client('emr')` | `aws emr` | Managed Hadoop/Spark |
| EMR Containers | `boto3.client('emr-containers')` | `aws emr-containers` | Serverless EMR on EKS |
| EMR Serverless | `boto3.client('emr-serverless')` | `aws emr-serverless` | Serverless EMR |
| Kinesis Analytics | `boto3.client('kinesisanalytics')` | `aws kinesisanalytics` | SQL on streaming data |
| Kinesis Analytics v2 | `boto3.client('kinesisanalyticsv2')` | `aws kinesisanalyticsv2` | Stream processing |
| OpenSearch Ingestion | `boto3.client('osis')` | `aws opensearchserverless` | Log/telemetry ingestion |
| Panorama | — | — | Computer vision at edge |
| Comprehend | `boto3.client('comprehend')` | `aws comprehend` | NLP, sentiment, entities |
| Comprehend Medical | `boto3.client('comprehendmedical')` | `aws comprehendmedical` | Healthcare NLP |
| Polly | `boto3.client('polly')` | `aws polly` | TTS (text-to-speech) |
| Rekognition | `boto3.client('rekognition')` | `aws rekognition` | Image/video analysis |
| Textract | `boto3.client('textract')` | `aws textract` | Document text extraction |
| Transcribe | `boto3.client('transcribe')` | `aws transcribe` | Speech-to-text |
| Translate | `boto3.client('translate')` | `aws translate` | Language translation |
| Kendra | `boto3.client('kendra')` | `aws kendra` | Intelligent search |
| Kendra Ranking | `boto3.client('kendra-ranking')` | `aws kendra-ranking` | Rerank search results |
| Personalize | `boto3.client('personalize')` | `aws personalize` | Real-time recommendations |
| Personalize Runtime | `boto3.client('personalize-runtime')` | `aws personalize-runtime` | Live recommendation API |
| Personalize Events | `boto3.client('personalize-events')` | `aws personalize-events` | Event tracking |
| Forecast | `boto3.client('forecast')` | `aws forecast` | Time-series forecasting |
| Forecast Query | `boto3.client('forecastquery')` | `aws forecastquery` | Forecast queries |
| QuickSight | `boto3.client('quicksight')` | `aws quicksight` | BI/dashboarding |
| SageMaker | `boto3.client('sagemaker')` | `aws sagemaker` | ML platform |
| Augmented AI Runtime | `boto3.client('sagemaker-a2i-runtime')` | `aws sagemaker-a2i-runtime` | Human loops |
| SageMaker Edge | `boto3.client('sagemaker-edge')` | `aws sagemaker-edge` | Model deployment at edge |
| SageMaker FeatureStore | `boto3.client('sagemaker-featurestore-runtime')` | `aws sagemaker-featurestore-runtime` | Feature store |
| SageMaker Geospatial | `boto3.client('sagemaker-geospatial')` | `aws sagemaker-geospatial` | Satellite/geo ML |
| SageMaker Metrics | `boto3.client('sagemaker-metrics')` | `aws sagemaker-metrics` | ML model monitoring |
| SageMaker Runtime | `boto3.client('sagemaker-runtime')` | `aws sagemaker-runtime` | Inference endpoints |
| Clean Rooms | `boto3.client('cleanrooms')` | `aws cleanrooms` | Collaborative data analysis |
| Clean Rooms ML | `boto3.client('cleanroomsml')` | `aws cleanroomsml` | ML in Clean Rooms |
| HealthImaging | `boto3.client('medical-imaging')` | `aws medical-imaging` | Medical image storage |
| Lake Formation | `boto3.client('lakeformation')` | `aws lakeformation` | Data lake setup |
| DataExchange | `boto3.client('dataexchange')` | `aws dataexchange` | Data product sharing |
| Entity Resolution | `boto3.client('entityresolution')` | `aws entityresolution` | Record matching/merge |
| Customer Profiles | `boto3.client('customer-profiles')` | `aws customer-profiles` | Unified customer view |
| Location Service | `boto3.client('location')` | `aws location` | Maps/geofencing/routing |
| Location Maps v2 | `boto3.client('geo-maps')` | `aws geo-maps` | Maps tiles |
| Location Places v2 | `boto3.client('geo-places')` | `aws geo-places` | POI/place search |
| Location Routes v2 | `boto3.client('geo-routes')` | `aws geo-routes` | Route optimization |
| Braket | `boto3.client('braket')` | `aws braket` | Quantum computing |
| Kendra | `boto3.client('kendra')` | `aws kendra` | Enterprise search |

## 7. Serverless & Application Integration

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| Lambda | `boto3.client('lambda')` | `aws lambda` | Serverless functions |
| Lambda Core | `boto3.client('lambda-core')` | `aws lambda-core` | Lambda core APIs |
| Lambda MicroVMs | `boto3.client('lambda-microvms')` | `aws lambda-microvms` | Lambda isolation |
| Lambda Web | `boto3.client('lambda-web')` | `aws lambda-web` | Lambda web serving |
| SNS | `boto3.client('sns')` | `aws sns` | Pub/sub messaging |
| SQS | `boto3.client('sqs')` | `aws sqs` | Queue service |
| Step Functions | `boto3.client('stepfunctions')` | `aws stepfunctions` | Workflow orchestration |
| EventBridge | `boto3.client('events')` | `aws events` | Event bus/routing |
| EventBridge Pipes | `boto3.client('pipes')` | `aws pipes` | Event ingestion/transformation |
| EventBridge Scheduler | `boto3.client('scheduler')` | `aws scheduler` | Cron-style scheduling |
| EventBridge v2 | `boto3.client('events')` | — | (same) |
| MSK (Kafka) | `boto3.client('kafka')` | `aws kafka` | Managed Apache Kafka |
| MSK Connect | `boto3.client('kafkaconnect')` | `aws kafkaconnect` | Kafka connectors |
| AppSync | `boto3.client('appsync')` | `aws appsync` | GraphQL APIs |
| DynamoDB Streams | `boto3.client('dynamodbstreams')` | `aws dynamodbstreams` | Stream processing |
| Firehose | `boto3.client('firehose')` | `aws firehose` | Kinesis data delivery |
| Kinesis | `boto3.client('kinesis')` | `aws kinesis` | Stream data ingestion |
| SWF | `boto3.client('swf')` | `aws swf` | Step functions predecessor |
| Schemas | `boto3.client('schemas')` | `aws schemas` | Event schema registry |
| App Config | `boto3.client('appconfig')` | `aws appconfig` | Feature flags/deploy |
| App Config Data | `boto3.client('appconfigdata')` | `aws appconfigdata` | Config retrieval |
| Application Signals | `boto3.client('application-signals')` | `aws application-signals` | App signals OTel |
| CloudFormation | `boto3.client('cloudformation')` | `aws cloudformation` | IaC stack mgmt |
| Service Catalog | `boto3.client('servicecatalog')` | `aws servicecatalog` | Product catalog mgmt |
| AppRegistry | `boto3.client('servicecatalog-appregistry')` | `aws servicecatalog-appregistry` | App inventory |

## 8. Management & Governance

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| CloudFormation | `boto3.client('cloudformation')` | `aws cloudformation` | Infrastructure as code |
| CloudControl API | `boto3.client('cloudcontrol')` | `aws cloudcontrol` | Universal resource API |
| Systems Manager (SSM) | `boto3.client('ssm')` | `aws ssm` | Patching, run commands, docs |
| SSM Contacts | `boto3.client('ssm-contacts')` | `aws ssm-contacts` | Incident contact plans |
| SSM Incidents | `boto3.client('ssm-incidents')` | `aws ssm-incidents` | Incident management |
| SSM Quick Setup | `boto3.client('ssm-quicksetup')` | `aws ssm-quicksetup` | Rapid SSM config |
| SSM SAP | `boto3.client('ssm-sap')` | `aws ssm-sap` | SAP app management |
| SSM GUI Connect | `boto3.client('ssm-guiconnect')` | `aws ssm-guiconnect` | Browser-based desktop |
| Config Service | `boto3.client('configservice')` | `aws configservice` | Resource compliance |
| Control Tower | `boto3.client('controltower')` | `aws controltower` | Landing zone mgmt |
| Audit Manager | `boto3.client('auditmanager')` | `aws auditmanager` | Audit automation |
| Resilience Hub | `boto3.client('resiliencehub')` | `aws resiliencehub` | App resilience testing |
| Resilience Hub v2 | `boto3.client('resiliencehubv2')` | `aws resiliencehubv2` | Resilience APIs v2 |
| Well-Architected | `boto3.client('wellarchitected')` | `aws wellarchitected` | Architecture reviews |
| Service Quotas | `boto3.client('service-quotas')` | `aws service-quotas` | Service limit mgmt |
| Resource Groups | `boto3.client('resource-groups')` | `aws resource-groups` | Logical resource grouping |
| Resource Explorer | `boto3.client('resource-explorer-2')` | `aws resource-explorer-2` | Cross-account search |
| Resource Tagging API | `boto3.client('resourcegroupstaggingapi')` | `aws resourcegroupstaggingapi` | Tag-based search |
| Application Insights | `boto3.client('application-insights')` | `aws application-insights` | App monitoring |
| DevOps Guru | `boto3.client('devops-guru')` | `aws devops-guru` | Anomaly detection |
| Application Cost Profiler | `boto3.client('applicationcostprofiler')` | `aws applicationcostprofiler` | Cost profiling |
| Application Discovery | `boto3.client('discovery')` | `aws discovery` | On-prem app discovery |
| ARC Region Switch | `boto3.client('arc-region-switch')` | `aws arc-region-switch` | Cross-region failover |
| ARC Zonal Shift | `boto3.client('arc-zonal-shift')` | `aws arc-zonal-shift` | AZ shift |
| Backup | `boto3.client('backup')` | `aws backup` | Centralized backup |
| Backup Gateway | `boto3.client('backup-gateway')` | `aws backup-gateway` | On-prem backup gateway |
| Backup Search | `boto3.client('backupsearch')` | `aws backupsearch` | Cross-account backup search |
| DLM (Data Lifecycle) | `boto3.client('dlm')` | `aws dlm` | Snapshot lifecycle mgmt |
| GuardDuty | `boto3.client('guardduty')` | `aws guardduty` | Threat detection |
| Inspector | `boto3.client('inspector')` | `aws inspector` | Vuln assessment (v1) |
| Inspector 2 | `boto3.client('inspector2')` | `aws inspector2` | Vuln assessment (v2) |
| Inspector Scan | `boto3.client('inspector-scan')` | `aws inspector-scan` | Scan scheduling |
| Security Hub | `boto3.client('securityhub')` | `aws securityhub` | Security posture |
| Security Lake | `boto3.client('securitylake')` | `aws securitylake` | Centralized security data lake |
| Security IR | `boto3.client('security-ir')` | `aws security-ir` | Security incident response |
| Security Agent | `boto3.client('securityagent')` | `aws securityagent` | Security agent mgmt |
| Detective | `boto3.client('detective')` | `aws detective` | Root cause analysis |
| Health | `boto3.client('health')` | `aws health` | AWS service health events |
| HealthLake | `boto3.client('healthlake')` | `aws healthlake` | FHIR medical data |
| FinOps Engage | — | — | Cost optimization platform |
| Cost Optimization Hub | `boto3.client('cost-optimization-hub')` | `aws cost-optimization-hub` | Cost optimization recs |
| CloudTrail | `boto3.client('cloudtrail')` | `aws cloudtrail` | API audit logging |
| CloudTrail Data | `boto3.client('cloudtrail-data')` | `aws cloudtrail-data` | Data events |
| CloudWatch | `boto3.client('cloudwatch')` | `aws cloudwatch` | Metrics/alarms/logs |
| CloudWatch RUM | `boto3.client('rum')` | `aws rum` | Real user monitoring |
| CloudWatch Network Monitor | `boto3.client('networkmonitor')` | `aws networkmonitor` | Network latency monitoring |
| CloudWatch Internet Monitor | `boto3.client('internetmonitor')` | `aws internetmonitor` | Internet performance |
| CloudWatch Observability Access Mgr | `boto3.client('oam')` | `aws oam` | Observability access |
| CloudWatch Observability Admin | `boto3.client('observabilityadmin')` | `aws observabilityadmin` | Observability admin |
| CloudWatch Application Signals | `boto3.client('application-signals')` | — | OTel-based signals |
| X-Ray | `boto3.client('xray')` | `aws xray` | Distributed tracing |
| Synthetics | `boto3.client('synthetics')` | `aws synthetics` | Canaries/monitoring |
| CloudWatch Omni | `boto3.client('cloudwatchomni')` | `aws cloudwatchomni` | Unified observability |
| Trusted Advisor | `boto3.client('trustedadvisor')` | `aws trustedadvisor` | Best practices |
| User Notifications | `boto3.client('notifications')` | `aws notifications` | AWS notification mgmt |
| User Notifications Contacts | `boto3.client('notificationscontacts')` | `aws notificationscontacts` | Notification contacts |
| IT Service Mgmt (Continuum) | `boto3.client('continuum')` | `aws continuum` | ITSM integration |
| DevOps Agent | `boto3.client('devops-agent')` | `aws devops-agent` | CI/CD agent |

## 9. Security, Identity & Compliance

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| WAF | `boto3.client('waf')` | `aws waf` | Web Application Firewall (legacy) |
| WAF Regional | `boto3.client('waf-regional')` | `aws waf-regional` | Regional WAF |
| WAF v2 | `boto3.client('wafv2')` | `aws wafv2` | Web ACLs (current) |
| Shield | `boto3.client('shield')` | `aws shield` | DDoS protection |
| Macie | `boto3.client('macie2')` | `aws macie2` | PII/data discovery |
| KMS | `boto3.client('kms')` | `aws kms` | Encryption keys |
| ACM | `boto3.client('acm')` | `aws acm` | TLS certificates |
| Certificate Manager PCA | `boto3.client('acm-pca')` | `aws acm-pca` | Private CA |
| Signer | `boto3.client('signer')` | `aws signer` | Code/signing |
| Signer Data Plane | `boto3.client('signer-data')` | `aws signer-data` | Code signing API |
| Artifact | `boto3.client('artifact')` | `aws artifact` | Compliance docs/agreements |
| Cloud Directory | `boto3.client('clouddirectory')` | `aws clouddirectory` | Hierarchical data store |
| Directory Service | `boto3.client('ds')` | `aws ds` | AD integration |
| Directory Service Data | `boto3.client('ds-data')` | `aws ds-data` | Directory queries |
| Cognito | See Section 1 | — | User authentication |
| Secrets Manager | See Section 1 | — | Secret rotation |
| Payment Cryptography | `boto3.client('payment-cryptography')` | `aws payment-cryptography` | Crypto key mgmt |
| Payment Cryptography Data | `boto3.client('payment-cryptography-data')` | `aws payment-cryptography-data` | Crypto ops |
| GuardDuty | See Section 8 | — | Threat detection |
| Inspector 2 | See Section 8 | — | Vulnerability scan |
| Macie 2 | See Section 9 | — | Data discovery |
| Security Hub | See Section 8 | — | Security posture |
| Verified Permissions | See Section 1 | — | Custom authz |
| Firehose | `boto3.client('firehose')` | `aws firehose` | Data delivery (security context) |

## 10. Monitoring & Observability

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| CloudWatch | `boto3.client('cloudwatch')` | `aws cloudwatch` | Metrics, alarms, events |
| CloudWatch Logs | `boto3.client('logs')` | `aws logs` | Log ingestion/query |
| X-Ray | `boto3.client('xray')` | `aws xray` | Distributed tracing |
| CloudWatch RUM | `boto3.client('rum')` | `aws rum` | Real user monitoring |
| CloudWatch Synthetics | `boto3.client('synthetics')` | `aws synthetics` | Canary blue/green tests |
| CloudWatch Internet Monitor | `boto3.client('internetmonitor')` | `aws internetmonitor` | Internet perf |
| CloudWatch Network Monitor | `boto3.client('networkmonitor')` | `aws networkmonitor` | Cross-VPC latency |
| CloudWatch Observability Access Mgr | `boto3.client('oam')` | `aws oam` | Shared observability |
| CloudWatch Observability Admin | `boto3.client('observabilityadmin')` | `aws observabilityadmin` | Observability admin |
| CloudWatch Application Signals | `boto3.client('application-signals')` | — | OTel signals |
| CloudWatch Omni | `boto3.client('cloudwatchomni')` | `aws cloudwatchomni` | Unified view |
| CloudWatch Network Firewall | See Section 3 | — | Firewall logs |
| DevOps Guru | See Section 8 | — | Anomaly detection |
| GuardDuty | See Section 8 | — | Security monitoring |
| Health | See Section 8 | — | Service health |
| IoT SiteWise | `boto3.client('iotsitewise')` | `aws iotsitewise` | Industrial data |
| IoT FleetWise | `boto3.client('iotfleetwise')` | `aws iotfleetwise` | Vehicle data |
| Ground Station | `boto3.client('groundstation')` | `aws groundstation` | Satellite comms |
| Application Auto Scaling | See Section 2 | — | Scale metrics |
| Compute Optimizer | `boto3.client('compute-optimizer')` | `aws compute-optimizer` | Resource recs |
| Compute Optimizer Automation | `boto3.client('compute-optimizer-automation')` | `aws compute-optimizer-automation` | Auto apply recs |
| CloudWatch Application Signals | `boto3.client('application-signals')` | — | OTel app signals |

## 11. Developer Tools

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| CodeCommit | `boto3.client('codecommit')` | `aws codecommit` | Git repos |
| CodeBuild | `boto3.client('codebuild')` | `aws codebuild` | CI builds |
| CodePipeline | `boto3.client('codepipeline')` | `aws codepipeline` | CI/CD pipelines |
| CodeDeploy | `boto3.client('codedeploy')` | `aws codedeploy` | App deployment |
| CodeGuru Reviewer | `boto3.client('codeguru-reviewer')` | `aws codeguru-reviewer` | Code review (ML) |
| CodeGuru Security | `boto3.client('codeguru-security')` | `aws codeguru-security` | Security scan |
| CodeGuru Profiler | `boto3.client('codeguruprofiler')` | `aws codeguruprofiler` | App profiling |
| CodeArtifact | `boto3.client('codeartifact')` | `aws codeartifact` | Package repos |
| CodeCatalyst | `boto3.client('codecatalyst')` | `aws codecatalyst` | Dev environment |
| Cloud9 | `boto3.client('cloud9')` | `aws cloud9` | Cloud IDE |
| Proton | `boto3.client('proton')` | `aws pro` | Environment mgmt |
| Amplify | `boto3.client('amplify')` | `aws amplify` | Full-stack apps |
| Amplify Backend | `boto3.client('amplifybackend')` | `aws amplifybackend` | Backend mgmt |
| Amplify UI Builder | `boto3.client('amplifyuibuilder')` | `aws amplifyuibuilder` | UI component builder |
| Device Farm | `boto3.client('devicefarm')` | `aws devicefarm` | Mobile testing |
| Chime SDK | `boto3.client('chime')` | `aws chime` | Video/audio/IM |
| Chime SDK Identity | `boto3.client('chime-sdk-identity')` | `aws chime-sdk-identity` | Chime identity |
| Chime SDK Media Pipelines | `boto3.client('chime-sdk-media-pipelines')` | `aws chime-sdk-media-pipelines` | Media pipelines |
| Chime SDK Meetings | `boto3.client('chime-sdk-meetings')` | `aws chime-sdk-meetings` | Meeting mgmt |
| Chime SDK Messaging | `boto3.client('chime-sdk-messaging')` | `aws chime-sdk-messaging` | Messaging |
| Chime SDK Voice | `boto3.client('chime-sdk-voice')` | `aws chime-sdk-voice` | Voice SDK |
| Pinpoint | `boto3.client('pinpoint')` | `aws pinpoint` | Marketing comms |
| Pinpoint Email | `boto3.client('pinpoint-email')` | `aws pinpoint-email` | Email campaigns |
| Pinpoint SMS Voice | `boto3.client('pinpoint-sms-voice')` | `aws pinpoint-sms-voice` | SMS/voice |
| Pinpoint SMS Voice v2 | `boto3.client('pinpoint-sms-voice-v2')` | `aws pinpoint-sms-voice-v2` | SMS/voice v2 |
| SES | `boto3.client('ses')` | `aws ses` | Simple Email Service |
| SES v2 | `boto3.client('sesv2')` | `aws sesv2` | Email v2 |
| Lex Model Building | `boto3.client('lex-models')` | `aws lex-models` | Chatbot builder |
| Lex Runtime | `boto3.client('lex-runtime')` | `aws lex-runtime` | Chatbot runtime |
| Lex v2 Models | `boto3.client('lexv2-models')` | `aws lexv2-models` | Chatbot v2 builder |
| Lex v2 Runtime | `boto3.client('lexv2-runtime')` | `aws lexv2-runtime` | Chatbot v2 runtime |
| IoT Things Graph | `boto3.client('iotthingsgraph')` | `aws iotthingsgraph` | IoT flow graphs |
| IoT Device Advisor | `boto3.client('iotdeviceadvisor')` | `aws iotdeviceadvisor` | IoT device cert |
| Code Connections | `boto3.client('codeconnections')` | `aws codeconnections` | External code repos |
| CodeStar Connections | `boto3.client('codestar-connections')` | `aws codestar-connections` | External repos |
| CodeStar Notifications | `boto3.client('codestar-notifications')` | `aws codestar-notifications` | Build notifications |

## 12. Migration & Transfer

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| DMS (Migration Service) | `boto3.client('dms')` | `aws dms` | Database migration |
| DataSync | `boto3.client('datasync')` | `aws datasync` | Data transfer |
| Application Migration Service | `boto3.client('mgn')` | `aws mgn` | Lift-and-shift |
| Migration Hub | `boto3.client('mgh')` | `aws mgh` | Migration tracking |
| Migration Hub Config | `boto3.client('migrationhub-config')` | `aws migrationhub-config` | Migration group mgmt |
| Migration Hub Orchestrator | `boto3.client('migrationhuborchestrator')` | `aws migrationhuborchestrator` | Migration workflows |
| Migration Hub Strategy | `boto3.client('migrationhubstrategy')` | `aws migrationhubstrategy` | Strategy recommendations |
| Application Discovery Service | `boto3.client('discovery')` | `aws discovery` | On-prem app inventory |
| Serverless Application Repository | `boto3.client('serverlessrepo')` | `aws serverlessrepo` | SAM apps |
| Data Pipeline | `boto3.client('datapipeline')` | `aws datapipeline` | Scheduled data movement |
| Transfer Family | See Section 4 | — | SFTP/FTPS |
| Snowball | See Section 4 | — | Physical transfer |
| Application2Container | — | — | App containerization |

## 13. IoT & Edge

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| IoT Core | `boto3.client('iot')` | `aws iot` | Device connectivity |
| IoT Data Plane | `boto3.client('iot-data')` | `aws iot-data` | Device data ops |
| IoT Jobs Data | `boto3.client('iot-jobs-data')` | `aws iot-jobs-data` | Device job ops |
| IoT Managed Integrations | `boto3.client('iot-managed-integrations')` | `aws iot-managed-integrations` | Pre-built integrations |
| IoT FleetWise | See Section 10 | — | Vehicle telemetry |
| IoT Secure Tunneling | `boto3.client('iotsecuretunneling')` | `aws iotsecuretunneling` | Remote device access |
| IoT SiteWise | See Section 10 | — | Industrial data |
| IoT Things Graph | `boto3.client('iotthingsgraph')` | `aws iotthingsgraph` | IoT flow builder |
| IoT TwinMaker | `boto3.client('iottwinmaker')` | `aws iottwinmaker` | 3D facility models |
| IoT Wireless | `boto3.client('iotwireless')` | `aws iotwireless` | LoraWAN/Cellular |
| Greengrass | `boto3.client('greengrass')` | `aws greengrass` | Local compute (legacy) |
| Greengrass v2 | `boto3.client('greengrassv2')` | `aws greengrassv2` | Local compute (current) |
| LocalZones / Wavelength | Part of EC2 | — | Edge compute regions |
| Outposts | See Section 2 | — | Dedicated on-prem |

## 14. Business Applications

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| Connect | `boto3.client('connect')` | `aws connect` | Contact center |
| Connect Contact Lens | `boto3.client('connect-contact-lens')` | `aws connect-contact-lens` | Analytics/transcripts |
| Connect Campaigns | `boto3.client('connectcampaigns')` | `aws connectcampaigns` | Outbound campaigns |
| Connect Campaigns v2 | `boto3.client('connectcampaignsv2')` | `aws connectcampaignsv2` | Campaigns v2 |
| Connect Cases | `boto3.client('connectcases')` | `aws connectcases` | Case mgmt |
| Connect Health | `boto3.client('connecthealth')` | `aws connecthealth` | Health checks |
| Connect Participant | `boto3.client('connectparticipant')` | `aws connectparticipant` | Participant API |
| Chime | See Section 11 | — | Video conferencing |
| AppFabric | `boto3.client('appfabric')` | `aws appfabric` | SaaS app integration |
| IVS | `boto3.client('ivs')` | `aws ivs` | Interactive video |
| IVS Realtime | `boto3.client('ivs-realtime')` | `aws ivs-realtime` | Low-latency live video |
| IVS Chat | `boto3.client('ivschat')` | `aws ivschat` | Video chat |
| MediaConnect | `boto3.client('mediaconnect')` | `aws mediaconnect` | Live video transport |
| MediaLive | `boto3.client('medialive')` | `aws medialive` | Live video production |
| MediaPackage | `boto3.client('mediapackage')` | `aws mediapackage` | Video packaging |
| MediaPackage v2 | `boto3.client('mediapackagev2')` | `aws mediapackagev2` | Video packaging v2 |
| MediaPackage VOD | `boto3.client('mediapackage-vod')` | `aws mediapackage-vod` | Video on demand |
| MediaStore | `boto3.client('mediastore')` | `aws mediastore` | Video storage |
| MediaStore Data | `boto3.client('mediastore-data')` | `aws mediastore-data` | Media data ops |
| MediaTailor | `boto3.client('mediatailor')` | `aws mediatailor` | Video ad insertion |
| Amazon WorkDocs | `boto3.client('workdocs')` | `aws workdocs` | Document sharing |
| Amazon WorkMail | `boto3.client('workmail')` | `aws workmail` | Managed email/calendar |
| WorkMail Message Flow | `boto3.client('workmailmessageflow')` | `aws workmailmessageflow` | Email content mgmt |
| WorkSpaces | `boto3.client('workspaces')` | `aws workspaces` | Virtual desktops |
| WorkSpaces Instances | `boto3.client('workspaces-instances')` | `aws workspaces-instances` | Instance mgmt |
| WorkSpaces Thin Client | `boto3.client('workspaces-thin-client')` | `aws workspaces-thin-client` | Thin client mgmt |
| WorkSpaces Web | `boto3.client('workspaces-web')` | `aws workspaces-web` | Web-based desktop |
| Amazon Connect Wisdom | `boto3.client('wisdom')` | `aws wisdom` | Agent assistance |
| AgentSync | — | — | Workforce mgmt |
| Transcribe Call Analytics | — | — | Call transcription |
| Translate Document | — | — | Document translation |
| Rekognition Content Moderation | — | — | Image moderation |

## 15. Financial Operations

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| Cost Explorer | `boto3.client('ce')` | `aws ce` | Cost analysis |
| Budgets | `boto3.client('budgets')` | `aws budgets` | Cost budgets/alerts |
| Billing | `boto3.client('billing')` | `aws billing` | Billing overview |
| Billing Conductor | `boto3.client('billingconductor')` | `aws billingconductor` | Custom billing |
| Pricing | `boto3.client('pricing')` | `aws pricing` | Product pricing API |
| Savings Plans | `boto3.client('savingsplans')` | `aws savingsplans` | Savings plan mgmt |
| CUR (Cost & Usage Report) | `boto3.client('cur')` | `aws cur` | Detailed cost reports |
| BCM Dashboards | `boto3.client('bcm-dashboards')` | `aws bcm-dashboards` | Cost dashboards |
| BCM Data Exports | `boto3.client('bcm-data-exports')` | `aws bcm-data-exports` | Cost data export |
| BCM Pricing Calculator | `boto3.client('bcm-pricing-calculator')` | `aws bcm-pricing-calculator` | Pricing estimates |
| BCM Recommended Actions | `boto3.client('bcm-recommended-actions')` | `aws bcm-recommended-actions` | Cost recs |
| Free Tier | `boto3.client('freetier')` | `aws freetier` | Free tier tracking |
| Marketplace Metering | `boto3.client('meteringmarketplace')` | `aws meteringmarketplace` | Usage metering |
| Marketplace Catalog | `boto3.client('marketplace-catalog')` | `aws marketplace-catalog` | Product mgmt |
| Marketplace Deployment | `boto3.client('marketplace-deployment')` | `aws marketplace-deployment` | Deploy products |
| Marketplace Entitlement | `boto3.client('marketplace-entitlement')` | `aws marketplace-entitlement` | Entitlement lookup |
| Marketplace Commerce Analytics | `boto3.client('marketplacecommerceanalytics')` | `aws marketplacecommerceanalytics` | Sales analytics |
| Invoicing | `boto3.client('invoicing')` | `aws invoicing` | Invoice management |
| Tax Settings | `boto3.client('taxsettings')` | `aws taxsettings` | Tax configuration |
| Supply Chain | `boto3.client('supplychain')` | `aws supplychain` | Supply chain analytics |
| Sustainability | `boto3.client('sustainability')` | `aws sustainability` | Sustainability metrics |

## 16. Specialty / Vertical Services

| Service | boto3 Module | CLI Command | Purpose |
|---------|-------------|-------------|---------|
| Bedrock | `boto3.client('bedrock')` | `aws bedrock` | Foundation models |
| Bedrock Runtime | `boto3.client('bedrock-runtime')` | `aws bedrock-runtime` | Model inference |
| Bedrock Agent | `boto3.client('bedrock-agent')` | `aws bedrock-agent` | Agent orchestration |
| Bedrock Agent Runtime | `boto3.client('bedrock-agent-runtime')` | `aws bedrock-agent-runtime` | Agent invoke |
| Bedrock Agent Core | `boto3.client('bedrock-agentcore')` | `aws bedrock-agentcore` | Agent core APIs |
| Bedrock Agent Core Control | `boto3.client('bedrock-agentcore-control')` | `aws bedrock-agentcore-control` | Agent control |
| Bedrock Data Automation | `boto3.client('bedrock-data-automation')` | `aws bedrock-data-automation` | Data pipeline automation |
| Bedrock Data Automation Runtime | `boto3.client('bedrock-data-automation-runtime')` | `aws bedrock-data-automation-runtime` | Data pipeline runtime |
| Rekognition | See Section 6 | — | Image/video AI |
| Kendra | See Section 6 | — | Enterprise search |
| Clean Rooms | See Section 6 | — | Collaborative analytics |
| HealthImaging | See Section 6 | — | Medical imaging |
| HealthLake | See Section 8 | — | FHIR medical data |
| Braket | See Section 6 | — | Quantum computing |
| GameLift | `boto3.client('gamelift')` | `aws gamelift` | Game server hosting |
| GameLift Streams | `boto3.client('gameliftstreams')` | `aws gameliftstreams` | Game streaming |
| Location Service | See Section 6 | — | Maps/geofencing |
| Ground Station | See Section 10 | — | Satellite downlink |
| Omni | `boto3.client('omics')` | `aws omics` | Genomics research |
| Timestream | See Section 5 | — | Time-series DB |
| Timestream InfluxDB | See Section 5 | — | Managed InfluxDB |
| Textract | See Section 6 | — | Document AI |
| Fraud Detector | `boto3.client('frauddetector')` | `aws frauddetector` | Fraud detection ML |
| Voice ID | `boto3.client('voice-id')` | `aws voice-id` | Speaker verification |
| Machine Learning | `boto3.client('machinelearning')` | `aws machinelearning` | Simple ML (legacy) |
| CloudSearch | `boto3.client('cloudsearch')` | `aws cloudsearch` | Search service |
| CloudSearch Domain | `boto3.client('cloudsearchdomain')` | `aws cloudsearchdomain` | Search indexing |
| SimpleDB | `boto3.client('sdb')` | `aws sdb` | Simple DB (legacy) |
| SimpleDB v2 | `boto3.client('simpledbv2')` | `aws simpledbv2` | SimpleDB v2 |
| RTB Fabric | `boto3.client('rtbfabric')` | `aws rtbfabric` | Ad tech platform |
| AI Ops | `boto3.client('aiops')` | `aws aiops` | AIOps automation |
| Agent Registry | `boto3.client('agent-registry')` | `aws agent-registry` | Agent discovery |
| Agent Registry Control | `boto3.client('agent-registry-control')` | `aws agent-registry-control` | Agent control |
| Agent Toolkit | — | `aws agent-toolkit` | Agent tool kit |
| Q Business | `boto3.client('qbusiness')` | `aws qbusiness` | Enterprise AI assistant |
| Q Apps | `boto3.client('qapps')` | `aws qapps` | AI-powered apps |
| Q Connect | `boto3.client('qconnect')` | `aws qconnect` | Q assistant integration |
| Textract | `boto3.client('textract')` | `aws textract` | Document extraction |
| Transcribe | See Section 6 | — | Speech recognition |
| Translate | See Section 6 | — | Language translation |
| Polly | See Section 6 | — | Text-to-speech |
| Comprehend | See Section 6 | — | NLP |
| Elemental Inference | `boto3.client('elementalinference')` | `aws elementalinference` | Media AI inference |

## 17. Multi-Language SDK Mapping

### Python (boto3) — Primary for automation
```python
import boto3

# Example: EC2 listing
ec2 = boto3.client('ec2', region_name='us-east-1')
instances = ec2.describe_instances()

# Example: S3 listing
s3 = boto3.client('s3')
buckets = s3.list_buckets()

# Common base methods:
client.list_***()     # list resources
client.describe_***() # describe resources  
client.get_***()      # get single resource
client.put_***()      # create/update
client.create_***()   # create
client.delete_***()   # delete
client.update_***()   # update
client.start_***()    # start
client.stop_***()     # stop
```

### CLI equivalents
```bash
aws <service> list-***        # list
aws <service> describe-***    # describe
aws <service> get-***         # get
aws <service> put-***         # create/update
aws <service> create-***      # create
aws <service> delete-***      # delete
aws <service> update-***      # update
aws <service> start-***       # start
aws <service> stop-***        # stop
```

### Other SDKs (same service names, different client classes)

| Language | SDK | Client instantiation |
|----------|-----|---------------------|
| JavaScript/Node.js | `@aws-sdk/client-*` | `new EC2Client({ region: 'us-east-1' })` |
| Java | `aws-sdk-java-v2` | `Ec2Client.builder().region(Region.US_EAST_1).build()` |
| Go | `github.com/aws/aws-sdk-go-v2/service/ec2` | `ec2.NewFromConfig(cfg)` |
| .NET | `AWSSDK.Core` | `new AmazonEC2Client()` |
| Ruby | `aws-sdk` | `Aws::EC2::Client.new(region: 'us-east-1')` |
| Rust | `aws-sdk-ec2` | `Ec2Client::from_config(cfg).await` |
| TypeScript | `@aws-sdk/client-*` | `new EC2Client({})` |

## 18. AWS CLI Quick Reference

**Version:** AWS CLI 2.40.2 (current)

### Global Options
```
--debug               Turn on debug logging
--endpoint-url URL    Override default URL
--no-verify-ssl       Skip SSL verification
--no-paginate         Disable auto-pagination
--output json|text|table|yaml|yaml-stream|off
--query JMESPath      Filter response
--profile NAME        Use named profile
--region REGION       Override region
--version             Show version
--color on|off|auto   Color output
```

### Core Services for Management Harness

| CLI | What it does |
|-----|-------------|
| `aws ec2` | Most critical: instances, VPCs, subnets, security groups, SGs, AMIs, volumes, snapshots, routes, gateways, peering, flow logs, tags |
| `aws iam` | Users, groups, roles, policies, MFA, access keys, password policy, server certs |
| `aws sts` | AssumeRole, GetCallerIdentity, GetSessionToken, web identity federation |
| `aws s3` / `aws s3api` | Bucket/object CRUD, lifecycle, ACLs, CORS, bucket policies |
| `aws rds` | DB instances, clusters, snapshots, parameter groups, subnet groups, options groups |
| `aws cloudformation` | Stacks, templates, changesets, imports |
| `aws lambda` | Functions, layers, event mappings, aliases, versions, concurrency |
| `aws dynamodb` | Tables, items, queries, scans, backups, streams |
| `aws ecs` / `aws eks` | Container orchestration |
| `aws cloudwatch` | Metrics, alarms, log groups, subscriptions |
| `aws ssm` | Parameter Store, Run Command, Patch Manager, Session Manager, Automation |
| `aws organizations` | Accounts, OU, SCPs, policies, trust deletion, consolidated billing |
| `aws configservice` | Rules, deliveries, evaluators, conformance packs |
| `aws backup` | Vaults, plans, selections, jobs, recovery points |
| `aws guardduty` | Findings, detectors, members, filters |
| `aws securityhub` | Standards, findings, products |
| `aws route53` | Hosted zones, record sets, health checks |
| `aws kms` | Keys, encryption, grants, rotation |
| `aws secretsmanager` | Secrets, rotation, versions |
| `aws lambda` | Serverless functions |
| `aws sns` / `aws sqs` | Messaging |
| `aws elbv2` | Load balancers, targets, listeners, rules |
| `aws autoscaling` | Groups, launch configs/templates, policies |
| `aws events` | Event buses, rules, targets |
| `aws stepfunctions` | State machines, executions |
| `aws account` | Account info, contact, regions, aliases, tags |
| `aws budgets` | Cost budgets, alerts, notifications |
| `aws ce` | Cost explorer, tags, segments, forecasts |
| `aws cur` | Cost and usage reports |
| `aws service-quotas` | Service limits |
| `aws resource-explorer-2` | Cross-account resource search |
| `aws cloudtrail` | Trails, events, lookup |

### Regions & Endpoints
All services follow the pattern: `<service>.<region>.amazonaws.com`
- Default region: `us-east-1`
- Use `aws ec2 describe-regions` to list all
- Use `aws ec2 describe-availability-zones --region <region>` for AZs

### Credentials
```bash
# Profiles in ~/.aws/credentials
aws configure --profile harness

# Or environment variables
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...   # for temporary creds
AWS_DEFAULT_REGION=...
```

### Pagination
```python
# boto3 paginators
paginator = client.get_paginator('list_instances')
for page in paginator.paginate():
    ...

# CLI pagination
aws ec2 describe-instances --region us-east-1 --output json
```

---

## Infrastructure Summary

| Metric | Value |
|--------|-------|
| Geographic Regions | 39 |
| Availability Zones | 124 |
| Edge Locations (CloudFront) | 400+ |
| Upcoming | 7 more AZs, 2 new regions (Saudi Arabia, Chile) |

### Regions by Continent (current):
- **North America (9):** US East (N. Virginia), US East (Ohio), US West (Oregon), US West (N. California), Canada (Central), Canada West (Calgary), Mexico (Central), US GovCloud East, US GovCloud West
- **South America (1):** South America (São Paulo)
- **Europe (8):** Europe (West), Europe (Central), Europe (West2), Europe (Stockholm), Europe (Paris), Europe (Zurich), Europe (Frankfurt), Europe (Ireland)
- **Middle East (3):** Middle East (Bahrain), Middle East (UAE - Abu Dhabi)
- **Africa (1):** Africa (Cape Town)
- **Asia Pacific (8):** Asia Pacific (Tokyo), Asia Pacific (Seoul), Asia Pacific (Osaka), Asia Pacific (Mumbai), Asia Pacific (Singapore), Asia Pacific (Sydney), Asia Pacific (Melbourne), Asia Pacific (Jakarta)
- **Australia/New Zealand (1):** Australia (Sydney)

---

## Key Patterns for Management Harness

### CRUD Pattern
Most AWS services follow a consistent verb pattern:
- `Create*` → Create resources
- `Describe*` / `List*` → Read/query resources
- `Get*` → Get single resource state/details
- `Put*` → Update/create
- `Update*` → Modify existing
- `Delete*` → Remove
- `Start*` / `Stop*` → Lifecycle control
- `Enable*` / `Disable*` → Toggle features

### API Rate Limits
- Most services: 5-20 RPS per API call (varies by service)
- EC2: ~10-50 RPS depending on operation
- S3: ~5,500 PUT/COPY/POST/DELETE per second per prefix
- Use CloudFormation/Stack sets for bulk operations
- Use `--no-paginate` if you only need first page

### Common Error Patterns
- `AccessDenied` → IAM permissions issue
- `InvalidParameter` → Wrong parameter value
- `ResourceNotFound` → Resource doesn't exist
- `Throttling` → Rate limited, implement backoff
- `ServiceQuotaExceeded` → Hit service limit

---

*This reference was compiled from boto3 documentation, AWS CLI 2.40.2 reference, and AWS Products page (2025). Always verify with the [official AWS documentation](https://docs.aws.amazon.com/) for the most current information.*
