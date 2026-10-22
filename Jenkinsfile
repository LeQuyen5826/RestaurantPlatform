// CI/CD: GitHub -> Jenkins -> Restore -> Build -> Test -> Publish -> Deploy (IIS) -> Verify
// Chạy trên Jenkins Windows. Dùng với Multibranch Pipeline (nhánh khác main chỉ chạy tới Test) hoặc Pipeline thường.
pipeline {
  agent any
  options {
    timestamps()
    disableConcurrentBuilds()          // không cho hai lần deploy chạy chồng nhau
    buildDiscarder(logRotator(numToKeepStr: '20'))
    timeout(time: 20, unit: 'MINUTES')
  }
  triggers { githubPush() }            // GitHub webhook -> /github-webhook/
  environment {
    DEPLOY_ROOT = 'C:\\wwwroot\\booking'
    VITE_BASE   = '/booking/'          // frontend chạy dưới http://localhost/booking
    SITE_URL    = 'http://localhost/booking'
    PYTHONUTF8  = '1'
  }
  stages {
    stage('Checkout') {
      steps {
        checkout scm
        bat 'git log -1 --oneline'
      }
    }
    stage('Restore') {
      steps {
        bat 'py -3.12 -m venv .venv'
        bat '.venv\\Scripts\\python -m pip install -r backend\\requirements.txt --disable-pip-version-check'
        dir('frontend') { bat 'npm ci' }
      }
    }
    stage('Build') {
      steps {
        dir('frontend') { bat 'npm run build' }                       // tsc --noEmit (lỗi kiểu/cú pháp) + vite build
        bat '.venv\\Scripts\\python -m compileall -q backend\\app'    // lỗi cú pháp Python
      }
    }
    stage('Test') {
      steps {
        dir('backend') { bat '..\\.venv\\Scripts\\python -m pytest --junitxml=..\\test-results.xml' }
      }
      post { always { junit allowEmptyResults: true, testResults: 'test-results.xml' } }
    }
    stage('Publish') {
      steps {
        powershell './deploy/publish.ps1'
        archiveArtifacts artifacts: 'publish/**', fingerprint: true
      }
    }
    stage('Deploy') {
      // Chỉ nhánh main mới triển khai; nhánh khác dừng ở Publish
      when { expression { (env.BRANCH_NAME ?: env.GIT_BRANCH ?: '') ==~ /(origin\/)?main/ } }
      steps {
        powershell "./deploy/deploy.ps1 -Source '${env.WORKSPACE}\\publish' -Root '${env.DEPLOY_ROOT}'"
      }
    }
    stage('Verify') {
      when { expression { (env.BRANCH_NAME ?: env.GIT_BRANCH ?: '') ==~ /(origin\/)?main/ } }
      steps { powershell "./deploy/verify.ps1 -BaseUrl '${env.SITE_URL}'" }
      post {
        failure {
          echo 'Verify that bai -> rollback ve ban truoc'
          powershell "./deploy/deploy.ps1 -Rollback -Root '${env.DEPLOY_ROOT}'"
        }
      }
    }
  }
  post {
    success { echo 'Pipeline thanh cong' }
    failure { echo 'Pipeline that bai - ban dang chay tren IIS khong bi thay doi (hoac da rollback)' }
  }
}
