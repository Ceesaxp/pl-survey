#!/usr/bin/perl


package survey;

use strict qw/vars/;
use warnings;
use CGI qw/:standard/;
use CGI::Cookie;
use CGI::Carp qw/fatalsToBrowser warningsToBrowser/;
use XML::Simple;
use HTTP::Date qw/time2iso time2str/;
use FileHandle;
use Data::Dumper; # for debugging purposes, mostly
use vars qw/$q $path $survey_type/;

use constant VERSION => '0.1';
use constant CONFIG_DIR => 'cgi-data/surveys';
#use constant SCRIPT_URL => 'http://localhost:8888/cgi-bin/surveys.cgi';
#use constant SCRIPT_URL => 'http://vkocmedb601.eur.nsroot.net/cgi-bin/surveys.cgi';
use constant SCRIPT_URL => '/cgi-bin/surveys.cgi';
use constant COOKIE_NAME => 'net.nsroot.vkocmedb601.cgi.surveys.soe';

# A little help for debugginh...
$ENV{REQUEST_METHOD} = 'GET' unless defined $ENV{REQUEST_METHOD};

$q = new CGI;
$path = $q->path_info();
$survey_type = 'Surveys';
#$| = 1; # Tell Perl not to buffer our output

# HTTP method processing routines
#
# They all take PATH regexp and code block CODE as parameter, compare current
# path_info to the PATH regexp and execute CODE block if they match.
sub GET($$) {
    my ($path, $code) = @_;
    return unless $q->request_method eq 'GET' or $q->request_method eq 'HEAD';
    return unless $q->path_info =~ $path;
    $code->();
    exit;
}

sub POST($$) {
    my ($path, $code) = @_;
    return unless $q->request_method eq 'POST';
    return unless $q->path_info =~ $path;
    $code->();
    exit;
}

sub PUT($$) {
    my ($path, $code) = @_;
    return unless $q->request_method eq 'PUT';
    return unless $q->path_info =~ $path;
    $code->();
    exit;
}

sub DELETE($$) {
    my ($path, $code) = @_;
    return unless $q->request_method eq 'DELETE';
    return unless $q->path_info =~ $path;
    $code->();
    exit;
}


# Function: barf(STATUS,TITLE,MESSAGE)
#
# Sends HTTP status code STATUS in response, setting window title to TITLE and
# providing an optional MESSAGE text
sub barf($$;$) {
  my ($status, $title, $message) = @_;
  my $t = time2str();

  carp <<"EOH"
HTTP/1.0 $status
Date: $t
Content-Type: text/html; charset=utf-8

<html><head><title>$title</title></head><body><h1>$title</h1><p>$message</p></body></html>
EOH
}


# Function: getLocal_path(ID)
#
# Returns the ful path to a file requested.
sub get_local_path($) {
  my $id = shift;
  return CONFIG_DIR.'/'.$id.'.xml';
}

# Function: absolute_url(PATH)
#
# Returns full URL (host, port, path) to a given PATH
sub absolute_url($) {
    my $path = shift;
    return $q->url() . $path;
}



#
# Request dispatchers
#
eval {

  # catch the case when we're called directly, redirect to surveys list
  GET qr{^/?$} => sub {
    print $q->redirect( absolute_url('/survey/') );
  };

  # self documentatation
  GET qr{^/doc/?$} => sub {
    show_documentation();
  };

  # surveys list
  GET qr{^/survey/?$} => sub {
    standard_headers('Available Surveys');
    list_all_surveys();
  };

  # show survey
  GET qr{^/survey/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    my $survey = read_survey(get_local_path($sid));

    authenticate_user($sid) if ( $survey->{protected} eq 'yes'
                                 and !survey_cookie_set_p() );
    already_taken($sid) if defined $q->cookie("survey.$sid");
    standard_headers($survey->{'description'}, 0, $sid);
    build_form($sid, $survey);
    form_extras($sid);
  };


  # survey rporting
  GET qr{^/survey/report/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    my $survey = read_survey(get_local_path($sid));

    authenticate_admin_user ($sid) unless survey_admin_cookie_set_p();
    standard_headers ( $survey->{'description'} );
    build_survey_report ($sid);
  };

  # editing survey content !!FIXME!!
  GET qr{^/survey/edit/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    standard_headers('Edit Survey Parameters') && survey_edit_form($sid);
  };

  # accept answers to a survey
  POST qr{^/survey/answer/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    my $data = $q->Vars;
    my $survey = read_survey(get_local_path($data->{s}));
    my $sso = $q->cookie(COOKIE_NAME);
    my $qq = scalar keys %{$survey->{question}};
    my $pr = $survey->{passRate} || 0;

    set_survey_taken_cookie($sid);
    standard_headers('Your Results', 1);

    print $q->h1('You have completed the test, thank you.');

    # We will hash good/bad answers and combine the submission into $answers
    # with a bit of extra meta info.
    my (%good,%bad,$answers,$t,$f);

    # Log time, SOE ID and host IP
    $answers = time2iso().'|'.$sso.'|'.$ENV{REMOTE_ADDR}.'|'.$sid.'|';

    map {
      my ($x,$qkey) = split /:q/;
      my $qval = $data->{$_};
      $answers .= 'q'.$qkey.':'.$qval.'|' if defined $qkey;

      if (defined $qkey && defined $qval) {
        if ($survey->{question}->{$qkey}->{answerKey} eq $qval) {
          $good{$qkey} = $qval;
        } else {
          $bad{$qkey} = $qval unless $qkey eq ''; # remove extras, not answers
        }
      }
    } keys %{$data};

    $t = scalar keys %good;
    $f = scalar keys %bad;
    $answers .= $t.'|'.$f;
    save_score($sid,$answers);

    my $p = round($t / $qq * 100, 2);

    print $q->p('You have responded correctly to ',
                $q->span({class=>'you'},$t),
                ' out of ',
                $q->span({class=>'total'},$qq),
                ' questions ('.$q->span({class=>'pcnt'},$p).'% score).');
    print $q->p('Congratulations, this is a perfect score!') if ($f == 0);

    if ($survey->{verboseResults} =~ m/yes/i) {
      if ($t >= $pr) {
        # we want verbose results and survey has been passed (we have at least
        # $pr correct answers)
        if ($f > 0) {
          print $q->p('The following questions were not answered correctly:');
          my @errors;
          map {
            my $hint = $survey->{question}->{$_}->{'answerHint'};
            $hint = "($hint)" if defined $hint;
            push @errors, $q->li('Question',$_.': ',$survey->{question}->{$_}->{'text'},
                                 $q->ul($q->li({class=>'youra'},'Your response: ',
                                               $q->span({class=>'bad'},$bad{$_})),
                                        $q->li({class=>'correcta'},'Correct answer is: ',
                                               $q->strong(' '.$survey->{question}->{$_}->{answerKey}),
                                               $q->span({class=>'hint'},$hint))));
          } sort {$a <=> $b} keys %bad;
          print $q->ul({class=>'errors'}, @errors);
          print $q->p('If you want to improve your score, you can ',
                      $q->a({href=>"/cgi-bin/surveys.cgi/survey/$sid"},'take the survey again'),'.');
        }
      } else {
        print $q->p("You need to answer at least <span class='pass'>$pr</span> questions correctly to pass.",
                    'You have not been able to attain a passing grade and should ',
                    $q->a({href=>"/cgi-bin/surveys.cgi/survey/$sid"},'take the survey again').'.');
      }
    } else {
      # no verbosity required
    }

    print $q->end_html;
    exit;

  };


  # Autheticate and redirect to the survey if all is fine or to no_entry page if
  # not.
  POST qr{^/survey/auth/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    my $data = $q->Vars;
    my $survey = read_survey(get_local_path($sid));

    no_entry() if ($data->{skey} ne $survey->{accessKey});
    set_auth_cookie($data->{'sso'});

    # force a redirect
    print qq{<meta http-equiv="refresh" content="0;URL=/cgi-bin/surveys.cgi/survey/$sid">\n};
  };

  # update survey content
  PUT qr{^/survey/([-_[:alnum:]]+)$} => sub {
    barf 200, 'Got update request', "For survey $1.";
  }

};


# Function: survey_edit_form(SURVEY_ID)
#
# Build and display form to make changes to survey SURVEY_ID.
sub survey_edit_form ($) {
  my $sid = shift;
  print $q->p('Sorry, not yet implemented.'),
    p(a({href=>absolute_url('/survey/')},'Return to survey front')),
      end_html;
}


# Function: glob_dir()
#
# Reads CONFIG_DIR and returns the list of XML files in it.
#
# Why are we not using Perl's glob?  Because there was no ending to "mysterious"
# data losses with it -- shift not returning anything, etc.  And in any case --
# glob does a call to shell, whereas opendir does not.
sub glob_dir () {
  opendir(DIR, CONFIG_DIR);
  my @files = grep { /\.xml$/ } readdir(DIR);
  closedir(DIR);
  return @files;
}

# Function: list_all_surveys(STATUS)
#
# Lists all surveys that match STATUS (by default lists all defined surveys).
sub list_all_surveys(;$) {
  my $status = shift || 'ALL'; # by default we show all surveys
  my @surveys;
  my @page;

  for my $fn ( glob_dir() ) {
    next unless $fn =~ m{([^/]+)\.xml$};
    push @surveys, survey_title_link($1);
  }

  my $num_surveys = scalar @surveys || 0;
  push @page, $q->h2('Available surveys'),
    p('There ', ($num_surveys == 1 ? 'is' : 'are'),
      $num_surveys,
      'survey'.($num_surveys == 1 ? '' : 's'),
      ' defined') if ($num_surveys > 0);
  push @page, $q->h2('No surveys defined.') if ($num_surveys == 0);
  push @page, $q->ul(@surveys),
    $q->p('You can either run (take) any of these surveys or administer them.'),
      $q->p('Note that you have to be a survey admin to make changes to survey setups.'),
        $q->end_html;
  print @page;
  return;
}


# Function: read_survey(SURVEY_ID)
#
# Read survey definition file and store results in a hashref
#
# Parameters:
#   SURVEY_ID - Survey ID.  We will look for the file with name SURVEY_ID.xml in configuration directory.
#
# Returns:
#   Hash reference containing the representation of XML file.
sub read_survey ($) {
  my $survey_file = shift;
  confess "No name has been supplied for survey file!" unless defined $survey_file;
  confess "The file `$survey_file' does not exist!" if !(-e $survey_file);
  my $xs = new XML::Simple (ForceArray => 1, KeepRoot => 0, KeyAttr => ['key']);
  return $xs->XMLin($survey_file);
}


# Function: standard_headers(TITLE)
#
# Outputs a standard set of "front matter" -- fills in <HEAD> with required
# JS/CSS includes, creates <DIV> for branding data, fires off Event.observe()
# watchers.
#
# Parameters:
#   TITLE - page title (required)
#   NOHEADER - suppress output of HTTP header (optional, defaults to no suppress)
#   SURVEY_ID - add form reset/clear JS (optional, defaults to nothing)
#
# Returns:
#   Outputs required HTML segment
sub standard_headers ($;$$$) {
  my $title = shift;
  my $noheader = shift || 0;
  my $sid = shift;
  my $stype = shift || 'Citi M&B ';
  my $js;
  my (@events, @output);

  push @events,
    "\$('$sid').getElements().each( function(s) { s.checked = false; } );\n" if defined $sid;
  push @events, "opts = { descriptor : '$stype $survey_type', descriptorColor : 'blue', approvedLogo : 'citigroup' }; var header = new Branding.Header('branding', opts);";

  $js = 'Event.observe(window, "load", function() { ';
  map { $js .= $_,"\n"; } @events;
  $js .= '});';

  push @output, $q->header(-charset=>'utf-8') unless $noheader;
  push @output, $q->start_html(-title=>$title,
                               -encoding=>'utf-8',
                               -style=>{'src'=>['/css/surveys.css','/css/light.css']},
                               -script=>
                               [ { -type => 'text/javascript',
                                   -src      => '/lib/prototype-1.6.js'
                                 },
                                 { -type => 'text/javascript',
                                   -src      => '/lib/branding.js'
                                 },
                                 $js
                               ] );
  push @output, $q->div( { id=>'branding' }, '' );
  push @output, $q->div( { id=>'navigation' }, breadcrubms($title, $sid) );
  print @output;
  return;
}


# Function breadcrumbs(SURVEY_ID)
#
# Builds 'bread crumbs' navigation strip
sub breadcrubms($$) {
  my ($title, $sid) = @_;
  my @bcrumbs;
  push @bcrumbs, $q->li( a( { href=>'/' }, 'Citi M&amp;B Home' ) );
  push @bcrumbs, $q->li( { class=>'leftTab' }, '' );
  push @bcrumbs, $q->li( a( { href=>absolute_url('/') }, 'Surveys Home' ) );
  if (defined $sid) {
    push @bcrumbs, $q->li( { class=>'leftTab' }, '' );
    push @bcrumbs, $q->li( a( { href=>absolute_url("/survey/$sid") }, $title) );
  }
  return $q->ul( {id=>'nav'}, @bcrumbs);
}

# Function: build_form(SURVEY_ID, SURVEYOBJ)
#
# Builds the survey form
#
# Parameters:
#   SURVEY_ID - Survey ID to build the form for (required)
#   SURVEYOBJ - Parsed survey hash to extract data from (required)
#
# Returns:
#   Outputs HTML form
sub build_form ($$) {
  my ($sid,$survey) = @_;
  my @pg;
  push @pg, $q->h2( {-class=>'surveyDescription'}, $survey->{'description'} );
  push @pg, $q->p( $survey->{'surveyInstructions'} );
  push @pg, $q->start_div( { -class => 'survey' } );
  push @pg, $q->start_form(-id=>"$sid", -method=>'post',
                       -action => absolute_url('')."/survey/answer/$sid");
  push @pg, $q->hidden(-name => 'mode', -value => 'r'),
    $q->hidden(-name => 's', -value => $sid);

  my @qaset;
  map {
    my (%l, @v, $answers);
    my $question = $survey->{'question'}->{$_};
    my $gr = "s$sid:q$_";
    my $ans = $question->{'answer'}; # shortcut reference to <answer>s
    my $type = $question->{'type'};

    # labels for radio/checkbox
    map { $l{$_} = $_.'. '.$$ans{$_}{content}; push @v,"$_"; } sort keys %$ans;

    if ($type eq 'radio' || $type eq 'boolean') {
      $answers = $q->radio_group(-name => $gr,
                                 -values => \@v,
                                 -linebreak => 'true',
                                 -default => '',
                                 -labels => \%l);
    } elsif ($type eq 'multi') {
      $answers = $q->checkbox_group(-name => $gr,
                                    -values => \@v,
                                    -linebreak => 'true',
                                    -labels => \%l);
    } elsif ($type eq 'comment') {
      my $rows = $question->{'rows'} || 3;
      my $cols = $question->{'cols'} || 40;
      $answers = $q->textarea(-name=>$gr,
                              -default=>'',
                              -rows=>$rows,
                              -columns=>$cols);
    }
    push @qaset, $q->li({-class=>'question'},
                        $q->span({class=>'question'}, $question->{'text'}),
                        $q->div({-class=>'answers'},$answers));

  } sort {$a <=> $b} keys %{$survey->{'question'}};

  push @pg, $q->ol({-class=>'qaset'}, @qaset);
  push @pg, $q->div({-id=>'pollSubmit',-class=>'submit'},
                    submit('submit','Submit'));
  print @pg;
  print $q->endform(),enddiv();
  return;
}


# Function: autheticate_user(SURVEY_ID)
#
# If a survey requires authentication -- show a login form, take user input and
# initiate authentication.
#
# Parameters:
#   SURVEY_ID - Survey ID to perform authentication for
sub authenticate_user ($) {
  my $sid = shift;
  standard_headers('Log in');
  print $q->div({id=>'auth'},
                $q->start_form(-method => 'post',
                               -action => absolute_url("/survey/auth/$sid")),
                $q->ul( {-id=>'signon'},
                        $q->li('Your SOE user name:',
                               $q->textfield('sso','',8,7)),
                        $q->li('Survey access key',
                               $q->password_field('skey','',8,50),
                               $q->span({class=>'warning'},
                                        '** Not your Windows/SOE/SSO password **'))),
                $q->div( {-class=>'submit'},
                         $q->submit('submit','Sign in')),
                $q->endform);
  exit;
}


# Function authenticate_admin_user (SID)
#
# Same as authenticate_user but for admin purposes
sub authenticate_admin_user ($) {
  return 1;
}



# Function: no_entry
#
# If a user provides wrong survey access key -- tell him just that, blank out
# his survey cookie and suggest that he should re-login.
sub no_entry {
  my $c = cookie(-name    => COOKIE_NAME,
                 -value   => '',
                 -expires => '-1d');
  barf 403, 'Not authorized', 'Access key you have supplied is not correct.';
  exit;
}


# Function: already_taken(SURVEY_ID)
#
# If "survey completed" cookie has been set, tell user that he has already done
# this survey/quiz, no need to re-take it (unless she insists).
#
# Parameters:
#   SURVEY_ID - ID for the survey
sub already_taken ($) {
  standard_headers('You have already completed this survey');
  print $q->h1('You have already taken this survey.'),$q->end_tml;
  exit;
}


# Function: debug_print(INFO)
#
# Print out debug information INFO into STDERR.
sub debug_print (@) {
  my @in = @_;
  map { print STDERR "*** DEBUG: $_\n"; } @in;
  return;
}


# Function: survey_title_link(ID)
#
# Returns a LI element that includes survey title, survey id and a link to
# survey page for a given survey ID.
sub survey_title_link ($) {
  my $sid = shift;
  my $s = read_survey(get_local_path($sid));
  my $css = 'active';
  my @sli;
  $css = 'inactive' if $s->{'active'} =~ m/^n/i;
  push @sli, $q->li( { class => $css },
                     a( { href => absolute_url('/survey/'.$sid) },
                        $s->{description}),' ',
                     a( { class => 'button', href => absolute_url('/survey/edit/'.$sid) }, 'Edit'), ' ',
                     span({class=>'small'},"[ $sid ]"));
  push @sli, ($css eq 'active' ? '' : span({class=>'status'},' — Inactive') );
  return join "\n", @sli;
  #return $x;
}

# Function: build_survey_report (SID)
#
# Reporting for a survey SID
sub build_survey_report ($) {
  my $sid = shift;
  my @rep;
  my $resp = read_survey_responses ($sid);
  my $survey = read_survey(get_local_path($sid));
  print $q->h1('Summary results for',$survey->{'description'});
  my $pass_rate = $survey->{'passRate'};
  #print $q->pre(Dumper($resp));
  #print $q->p($resp->{'2008-03-06'}->{'ap72658'}->{'2008-03-06 18:12:48'}->{'bad'});
  push @rep, $q->li('Total number of times taken:',
                    strong( $resp->{'times_total'} ),
                    ', details by day:',
                    $q->ul( map {
                      $q->li($_, ':', $resp->{$_}->{'times_day'}) if m/^\d{4}-\d{2}-\d{2}/;
                    } sort keys %{$resp} ));
  my ($pass, $fail);
  $pass = $fail = 0;

  debug_print(Dumper($resp));

  map {
    my $d = $_;
    map {
      my $u = $_;
      map {
        $pass++ if $_->[2] >= $pass_rate;
        $fail++ if $_->[2] < $pass_rate;
      } @{$resp->{$d}->{$u}};
    } sort keys %{$resp->{$d}} if ($d =~ m/^\d{4}-\d{2}-\d{2}/);
  } sort keys %{$resp};

  push @rep, $q->li('Passed: ', $pass);
  push @rep, $q->li('Failed: ', $fail);
  print $q->ul(@rep);
  return;
}


# Function read_survey_responses (SID)
#
# Read responses database in and arrange data in a hash for easy retreival in
# the reporting engine.
sub read_survey_responses ($) {
  my $sid = shift;
  my $db = {};  # define anonymous hash to hold database in
  open (DB, CONFIG_DIR.'/'.$sid.'.dat') or
    confess "Cannot open file ${sid}.dat: $!";

  while (<DB>) {
    chomp;
    s/\r$//; # strip CRLFs
    my @r = split /\|/;
    my @answers;
    map {
      m/q\d+:(.+)/;
      push @answers, $1;
    } @r[4..23];

    my ($d, $t) = split / /,$r[0];
    my $user = $r[1];

    my @rec = ( $r[0], \@answers, $r[24], $r[25] );
    push @{$db->{$d}->{$user}}, \@rec;
    $db->{$d}->{'times_day_user'}->{$user}++;
    $db->{$d}->{'times_day'}++;
    $db->{$user}->{'times_user'}++;
    $db->{'times_total'}++;
  }

  close (DB);
  return $db;
}

# Function: survey_cookie_set_p
#
# Returns boolean if a survey cookie has been set
sub survey_cookie_set_p {
  return defined $q->cookie(COOKIE_NAME);
}

# Same as above, but for admin interface
sub survey_admin_cookie_set_p {
  #return defined $q->cookie(ADMIN_COOKIE_NAME);
  return 1;
}


# Function set_auth_cookie
#
# Sets authenticated cooke
sub set_auth_cookie ($) {
  my ($val) = shift;
  my $cookie = $q->cookie(-name    => COOKIE_NAME,
                          -value   => $val,
                          -expires => '+1d');
  print $q->header(-cookie => $cookie);
  return;
}


# Function: set_survey_taken_cookie
#
# Sets cookie once the survey is taken.
sub set_survey_taken_cookie ($) {
  my $sid = shift;
  my $cookie = $q->cookie(-name    => "survey.$sid",
                          -value   => 'taken',
                          -expires => '+1w');
  print $q->header(-cookie => $cookie );
  return;
}

# Function save_score(SCORE)
#
# Saves SCORE into survey log
sub save_score ($$) {
  my ($sid,$score) = @_;
  my $fh = new FileHandle CONFIG_DIR.'/'.$sid.'.dat', O_WRONLY|O_APPEND|O_CREAT;
  if (defined $fh) {
    print $fh $score."\n";
    undef $fh;       # automatically closes the file
  } else {
    debug_print ('Bummer '.$!.': '.CONFIG_DIR.'/'.$sid.'.dat');
  }
  return;
}

# Function form_extras
sub form_extras($) {
  my $sid = shift;
  my $js="('$sid').getElements().each(function(s) { s.checked = false; });";
  print $q->script($js);
  return;
}

# Function: round
# Round a floating number to given number of decimals
#
# Parameters:
# $number - Floating number to round
# $precision - Number of decimal places to round to
#
# Caveats:
#
# Perl does not have a real rounding function.  One has to use build
# one's own.  This one is not particularly smart, for instance:
#
# round(12.30123, 2) - will return 12.3, not 12.30.
#
# round(-12.345, 1)  - will return -12.2, *not -12.3* as expected.
#
# The latter one mattaers little to us in our case, as we aren't
# planning to operate negative fractional numbers in survey counts :)
# The former is nuisance...
#
sub round {
    my($number) = shift;
    my($precision) = shift;
    return int($number*10**$precision + .5) / 10**$precision;
}


# Function show_documentation
#
# Self-documenting application this is! :)
sub show_documentation {
  standard_headers('Survey Application Documentation');
  print <<"EOD";
<div id="doc">

<h1>Survey System Documentation</h1>

<h2>General Overview</h2>

<p>Survey module has been designed to provide a simple yet elegant way to serve
a number of survey types.  It is built on top of a stock ActiveState Perl
distribution requiring no additional modules.  Configuration files are stored in
XML using custom <a href="#schema">XML schema</a>.  Survey results are kept as
<a href="#results">plain-text delimitted files</a>.  A number of <a
href="#options">survey options</a> is available.</p>

<h2 id="schema">Survey Definition File</h2>

<p>Survey configuration is stored in XML.  A separate XML survey definition file
is expected for each survey.  File name also acts as survey ID that is
cross-referenced within the CGI application.</p>

<p>Survey definition file must conform to following structure:</p>

<pre class="sample">
&lt;?xml version="1.0" encoding="utf-8"?>
&lt;survey id="sid200801"
        description="Trade Finance Assessment"
        validFrom="20080324"
        validTill="20080430"
        surveyType="Assessment"
        protected="no"
        accessKey="&lt;secret_code_word&gt;"
        verboseResults="yes"
        passRate="16"
        logUsers="yes"
        active="yes">

  &lt;surveyInstructions>
  ...
  &lt;/surveyInstructions>

  &lt;question key="1" type="radio" text="Which is not a type of Trade Finance?" answerKey="c">
    &lt;answer key="a">Trade Loans</answer>
    &lt;answer key="b">Receivables Purchase</answer>
    &lt;answer key="c">Collections</answer>
    &lt;answer key="d">Supplier Finance</answer>
  &lt;/question>
&lt;/survey>
</pre>

<p>You can <a
href="http://russia.citigroup.net/departments/cibtech/xml/def/survey.rnc">download</a>
compact <a href="#">RelaxNG</a> XML schema for survey defijnition file for use
with your XML editor.  <a
href="http://russia.citigroup.net/departments/cibtech/xml/def/survey.dtd">DTD</a>
and <a
href="http://russia.citigroup.net/departments/cibtech/xml/def/survey.xsd">XSD</a>
formats are also available.</p>


<h3 id="wf">Survey Types</h3>

<p>This application supports a variety of question/answer type surveys, namely:</p>

<dl>

<dt>Poll</dt>

<dd>Simplest type of a survey, only one question with a set of answers is
expected.  Typically, a poll is an anonymous survey, but administrator may
choose to log source IPs in order to filter multiple submissions from the same
host.  There are no right or wrong ansers.</dd>

<dt>Quiz or Assessment</dt>

<dd>Users are typically logged, questions have assignments of "correct" answers
and user results may have to accrue the lowest passing rate.  Optionally, a user
may be shown what are right and wrong answers and how well he or she
scored.</dd>

<dt>Questionairy or Survey</dt>

<dd>Similarly to poll, there are no rights or wrongs, but the number of
questions is not limited.  Full options to log user activities and user
access.</dd>

</dl>


<h3>Survey Attributes</h3>

<dl>

<dt id="id">id</dt>

<dd>Survey ID.  Must match with file name, i.e. if survey definition is saved as
<tt>sid200801.xml</tt>, <tt>id</tt> attrubute must be set to
<tt>sid200801</tt>.</dd>

<dt id="description">description</dt>

<dd>Short survey description.  A more elaborate decription and survey-taking
instructions should be included into <a
href="#surveyInstructions"><tt>surveyInstructions</tt></a> tag.</dd>

<dt id="validity">validFrom, validTill</dt>

<dd>Validity dates for the survey.  These are optional parameters, must express
validity interval in short ISO date format (i.e. YYYYMMDD).  If not set, survey
will be considered active forever or until <a href="#active"><tt>active</tt></a>
attribute is set to <tt>no</tt>.</dd>

<dt>surveyType</dt>

<dd>This attribute is used primarily for two purposes: as a naming paramter to
be used when building forms and results, as well as helping to define <a
href="#wf">survey flow</a>.</dd>

<dt>protected</dt>

<dd>Boolean, possible values are <tt>(yes|no)</tt>.  Restrict access to survey.
Requires <a href="#accessKey"><tt>accessKey</tt></a> to be set.</dd>

<dt id="accessKey">accessKey</dt>

<dd>Survey access key.  <strong>Caution:</strong> stored in plain text in survey
definition file!  Must be set if a survey is flagged as protected.</dd>

<dt id="verboseResults">verboseResults</dt>

<dd>Boolean, possible values are <tt>(yes|no)</tt>.  If set tp 'yes', at the end
of the survey user will be given detailed account of his or her answers.  If
survey is of quiz type, then comparison of rights and wrong will be done,
providing optional <a href="#answerHint"><tt>answerHint</tt></a> for the user,
explaing why a given answer is right.</dd>

<dt id="passRate">passRate</dt>

<dd>Sets minimal passing rate for a survey as a number of correct answers.
Totally irrelevant for polls and plain surveys, only works for quizes.</dd>

<dt id="logUsers">logUsers</dt>

<dd>Boolean, possible values are <tt>(yes|no)</tt>.  If set, then user will have
to login and results file will include his login details.</dd>

<dt id="active">active</dt>

<dd>Boolean, possible values are <tt>(yes|no)</tt>.  When set to 'no' will cause
a survey to be marked as inactive.  Accessing an inactive survey will not record
your answers.</dd>
</dl>

<h3>surveyInstructions</h3>

<p><tt>surveyInstructions</tt> tag can be used to provide additional information
(e.g. instructions) on particular survey usage.</p>

<h3>Questions Attributes</h3>

<dl>

<dt>key</dt>

<dd>Question key.</dd>

<dt>type</dt>

<dd>Question type.  One of (radio|multi|text).  If 'text' is selected, then you
can optionally modify the size of text area input by providing <tt>rows</tt> and
<tt>cols</tt> attributes.</dd>

<dt>answerKey</dt>

<dd>Correct anser assignment.  relevant only for quiz-type survey.  Multiple
answers in 'multi' typed question should be separated with commas.</dd>

<dt>answerHint</dt>

<dd>Explanation of why a given answer is correct.</dd>

<dt>text</dt>

<dd>Question text.</dd>

</dl>

<h3>Answer Attributes</h3>

<p>Answer has only one attribute: key.</p>

<h2 id="results">Results File</h2>

<p>Survey results file is a plain-text delimited file with pipe character ("|",
ASCII()) is used as a field delimiter.  The following sequence of fields is
recorded:</p>

<pre class="sample">
date_time_stamp|user_id|ip_address|survey_id|q1:a1|q2:a2|...|qN:aN|rights|wrongs
</pre>

<p>A sample results file presented below:</p>

<pre class="sample">
2008-03-19 17:45:59|ab12345|127.0.0.1|sid200801|q1:a|q2:a|q3:a|...|6|13
2008-03-19 18:33:13|bc23456|127.0.0.1|sid200801|q1:b|q2:a|q3:b|...|9|10
2008-03-19 18:36:21|de34567|127.0.0.1|sid200801|q1:c|q2:c|q3:a|...|9|10
</pre>

<p>In case of multiple answers to a question (when <a href="#type">question
type</a> is set to 'multi'), answer keys are separated by commas
(e.g. <tt>q2:a,d,f</tt>).  Free-text answers (when <a href="#type">question
type</a> is set to 'text') are stored in double quotes with new line characters
replaced by '\n', tab characters replaced with '\t' and pipe charcters replaced
by '\|' escapes:</p>

<pre class="sample">
q7:"An<span class="meta">\\t</span>answer with<span class="meta">\\n</span>character<span class="meta">\\|</span>escapes"
</pre>


<h2>Other Considerations/Caveats</h3>

<p>There are a few.</p>

</div>
EOD
  print $q->end_html;
}

# finish it
1;
