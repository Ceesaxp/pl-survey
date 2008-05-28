#!/usr/bin/perl

package survey;

use strict qw/vars/;
my $start = (times)[0];
#use warnings;
use utf8;

use CGI qw/:standard *div *table/;
use CGI::Cookie;
use CGI::Carp qw/fatalsToBrowser warningsToBrowser/;
use XML::Simple;
#use XML::Parser;
use HTTP::Date qw/time2iso time2str/;
use FileHandle;
use Data::Dumper; # for debugging purposes, mostly
use vars qw/$q $path $survey_type @pgdebug $debug $survey/;

use constant VERSION => '0.2';
use constant CONFIG_DIR => 'data/surveys';
use constant SCRIPT_URL => '/cgi-bin/surveys.cgi';
use constant COOKIE_NAME => 'net.nsroot.vkocmedb601.cgi.surveys.soe';

# A little help for debugginh...
$ENV{REQUEST_METHOD} = 'GET' unless defined $ENV{REQUEST_METHOD};

$q = new CGI;
$path = $q->path_info();
$survey_type = 'Surveys';

# Enable debugging
$debug = 0;
#binmode STDERR, ":utf8";
binmode STDOUT, ":utf8";

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


# Function: get_local_path(ID)
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


sub debug_trace ($@) {
  return unless $survey::debug;
  my $status = shift || 'info';
  my @msg = @_;
  push @pgdebug, p({class=>'debug_'.$status},@msg);
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
    print standard_headers('Available Surveys');
    debug_trace ('info','calling list_all_surveys');
    print list_all_surveys();
  };

  # show survey
  GET qr{^/survey/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    authenticate_user($sid) if ( $survey->{protected} eq 'yes'
                                  and !survey_cookie_set_p() );
    already_taken ($sid) if defined $q->cookie("survey.$sid");
    print standard_headers($survey->{'description'}, 0, $sid);
    print build_form($sid, $survey);
    print form_extras($sid);
  };

  # poll graph
  GET qr{^/survey/graph/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    print standard_headers($survey->{'description'}, 0, $sid);
    print show_survey_stats($sid);
  };

  # survey rporting
  GET qr{^/survey/report/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    authenticate_admin_user ($sid) unless survey_admin_cookie_set_p();
    print standard_headers ($survey->{'description'}, 0, $sid);
    print build_survey_report ($sid);
  };

  # editing survey content !!FIXME!!
  GET qr{^/survey/edit/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    print standard_headers('Edit Survey Parameters') && survey_edit_form($sid);
  };

  # accept answers to a survey
  POST qr{^/survey/answer/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    my $data = $q->Vars;
    validate_and_store_answers($sid, $data);
    exit;
  };


  # Autheticate and redirect to the survey if all is fine or to no_entry page if
  # not.
  POST qr{^/survey/auth/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    my $data = $q->Vars;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;

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
  debug_trace ('info','calling list_all_surveys', @files);
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
  return @page;
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
  return $xs->XMLin($survey_file) or debug_trace('error',$@);
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
    "\$\$('#$sid input[type=checkbox]').each( function(s) { s.checked = false; } );\n" if defined $sid;
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
  return @output;
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
    push @bcrumbs, $q->li( a( { href=>absolute_url("/surveys/$sid") }, $title) );
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
  my @page;
  push @page, $q->start_div( {-id=>'page'} );
  push @page, $q->h2( {-class=>'surveyDescription'}, $survey->{'description'} );
  push @page, $q->p( $survey->{'surveyInstructions'} );
  push @page, $q->start_div( { -class => 'survey' } );
  push @page, $q->start_form(-id=>"$sid", -method=>'post',
                           -action => absolute_url('')."/survey/answer/$sid");
  push @page, $q->hidden(-name => 'mode', -value => 'r'),
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
    push @qaset, $q->li($q->span({class=>'question'}, $question->{'text'}),
                        $q->div({-class=>'answers'},$answers));

  } sort {$a <=> $b} keys %{$survey->{'question'}};

  push @page, $q->ol({-class=>'qaset'}, @qaset);
  push @page, $q->div({-id=>'pollSubmit',-class=>'submit'},
                      submit('submit','Submit'));
  push @page, $q->endform();
  push @page, $q->end_div();
  push @page, $q->end_div();
  return @page;
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
  print standard_headers('Log in');
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
  print standard_headers('You have already completed this survey');
  print $q->h1('You have already taken this survey.'),$q->end_tml;
  exit;
}


# Function: debug_print(INFO)
#
# Print out debug information INFO into STDERR.
sub debug_print (@) {
  my $in = join "\n", @_;
  print STDERR "\n*** DEBUG: ${in}\n";
  return;
}


# Function: survey_title_link(ID)
#
# Returns a LI element that includes survey title, survey id and a link to
# survey page for a given survey ID.
sub survey_title_link ($) {
  my $sid = shift;
  debug_trace ('info','in survey_title_link');
  my $s = read_survey(get_local_path($sid));
  debug_trace ('info','done read_survey', $s);
  my $css = 'active';
  my @sli;
  $css = 'inactive' if $s->{'active'} =~ m/^n/i;
  push @sli, $q->li( { class => $css },
                     a( { href => absolute_url('/survey/'.$sid) }, $s->{description}),' ',
                     button_link('edit',$sid,'Edit'), ' ',
                     ( ($s->{'surveyType'} =~ m/poll|survey/i) ? button_link('graph', $sid, 'Results') : '' ),
                     span({class=>'small'},"[ $sid ]"),
                     ( $css eq 'active' ? '' : span( {class=>'status'}, ' — Inactive' ) ) );
  debug_trace ('info',@sli);
  return join "\n", @sli;
}


sub button_link ($$) {
  my ( $action, $sid, $link_title ) = @_;
  return $q->a( { class => 'button', href => absolute_url("/survey/$action/$sid") }, $link_title);
}

# Function: build_survey_report(SID)
#
# Reporting for a survey SID
sub build_survey_report ($) {
  my $sid = shift;
  my $responses = read_survey_responses($sid);
  $survey = read_survey(get_local_path($sid)) unless defined $survey;
  print $q->h1('Summary results for',$survey->{'description'});
  print $q->pre(Dumper($responses));
  return;
}


# Function read_survey_responses (SID)
#
# Read responses database in and arrange data in a hash for easy retreival in
# the reporting engine.
sub read_survey_responses ($) {
  my $sid = shift;
  my $db = {};  # define anonymous hash to hold database in
  open my $fh, CONFIG_DIR.'/'.$sid.'.db' || debug_trace('error',$@);
  binmode $fh, ':encoding(UTF-8)';
  my $s = read_survey(get_local_path($sid)); # local copy

  while (<$fh>) {
    next if (/^#/);             # skip comments
    my @r = split /\|/;
    my $l = (scalar @r) - 2;    # skip last 2 fields, irrelevant for polls
    $db->{'g_total'}++;         # increment total response counter
    map {
      my ($qkey,$answers) = split /:/;
      $qkey =~ s/^q//;          # strip off a leading 'q'
      # multiple choices (check boxes) need to be counted up differently
      my $mt = ( $s->{'question'}->{$qkey}->{'type'} eq 'multi' ? 1 : 0 );
      $db->{'resp'}->{$qkey}->{'total'}++ unless $mt;
      map {
        $db->{'resp'}->{$qkey}->{'a'}->{$_} += 1;
        $db->{'resp'}->{$qkey}->{'total'} += 1 if $mt;
      } split /\00/,$answers;
    } @r[4..$l];
  }

  close ($fh);
  return $db;
}

# Function: survey_cookie_set_p
#
# Returns boolean if a survey cookie has been set
sub survey_cookie_set_p {
  return defined $q->cookie(COOKIE_NAME);
}

# Same as above, but for admin interface -- FIXME
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
  my $fh = new FileHandle CONFIG_DIR.'/'.$sid.'.db', O_WRONLY|O_APPEND|O_CREAT;
  if (defined $fh) {
    print $fh $score."\n";
    undef $fh;       # automatically closes the file
  } else {
    debug_print ('Bummer '.$!.': '.CONFIG_DIR.'/'.$sid.'.dat');
  }
  return;
}


# Finction: sanatize_input(VALUE)
#
# Cleans input, brute force, at least for now.
sub sanatize_input($) {
  my $val = shift;
  my $html_tags = qr(p|a|i|b|em|strong|span|script|h[1-6]|li|ol|ul|dl|dt|dd|strike|sub|sub|font|style|br|form|input|button|table|td|tr|th|tbody|thead|tfoot|div);
  $val =~ s/\r//g;
  $val =~ s/\n/\\n/g;
  $val =~ s/<\/?${html_tags}[^>]*\/?>//g; # strip all listed HTML tags, very
                                          # crude
  return $val;
}


# Function: validate_and_store_answers
sub validate_and_store_answers ($$) {
  my $sid = shift;
  my $data = shift;
  $survey = read_survey(get_local_path($data->{'s'}));
  my $sso = $q->cookie(COOKIE_NAME) || 'ANON';
  my $qq = scalar keys %{$survey->{question}};
  my $pr = $survey->{passRate} || 0;

  set_survey_taken_cookie($sid); # not working?
  print standard_headers('Thank you', 1);

  # We will hash good/bad answers and combine the submission into $answers
  # with a bit of extra meta info.
  my (%good,%bad,$answers,$t,$f,@page);

  my $ip;
  $survey->{'logUsers'} =~ /yes|true/ ? $ip = $ENV{REMOTE_ADDR} : $ip = 'NOTSTORED';

  # Log time, SOE ID and host IP
  $answers = time2iso().'|'.$sso.'|'.$ip.'|'.$sid.'|';

  # iterate over hash keys in POST data and fillup good/bad hashes
  map {
    my ($x,$qkey) = split /:q/;
    my $qval = $data->{$_};
    $qval = sanatize_input($qval);
    $answers .= 'q'.$qkey.':'.$qval.'|' if defined $qkey;

    if (defined $qkey && defined $qval) {
      if ($survey->{question}->{$qkey}->{'answerKey'} eq $qval) {
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

  # the next set of actions is surveyType-dependant
  if ($survey->{'surveyType'} =~ m/test/i ||
      $survey->{'surveyType'} =~ m/assess/i) {
    # this is a test or an assessment
    push @page, $q->h1('You have completed the test, thank you.');
    my $p = round($t / $qq * 100, 2);
    push @page,
      $q->p("You have responded correctly to <strong>$t</strong> out of <strong>$qq</strong>",
            " questions (<span class='pcnt'>${p}\%</span> score).");
    push @page, $q->p('Congratulations, this is a perfect score!') if ($f == 0);

    if ($survey->{verboseResults} =~ m/yes/i) {
      if ($t >= $pr) {
        # user passed the test
        if ($f > 0) {
          push @page, $q->p('The following questions were not answered correctly:');
          my @errors;
          map {
            my $hint = $survey->{question}->{$_}->{'answerHint'};
            $hint = "($hint)" if defined $hint;
            push @errors, $q->li('Question',$_.': ',$survey->{'question'}->{$_}->{'text'},
                                 $q->ul($q->li({class=>'youra'},'Your response: ',
                                               $q->span({class=>'bad'},$bad{$_})),
                                        $q->li({class=>'correcta'},'Correct answer is: ',
                                               $q->strong(' '.$survey->{'question'}->{$_}->{'answerKey'}),
                                               $q->span({class=>'hint'},$hint))));
          } sort {$a <=> $b} keys %bad;
          push @page, $q->ul({class=>'errors'}, @errors);
          push @page, $q->p('If you want to improve your score, you can ',
                            $q->a({href=>"/cgi-bin/surveys.cgi/survey/$sid"},'take the survey again'),'.');
        }
      } else {
        # user did not pass
        push @page, $q->p("You need to answer at least <span class='pass'>$pr</span> questions correctly to pass.",
                          'You have not been able to attain a passing grade and should ',
                          $q->a({href=>"/cgi-bin/surveys.cgi/survey/$sid"},'take the survey again').'.');
      }
    }

  } elsif ($survey->{'surveyType'} =~ m/poll/i) {
    push @page, $q->h1('Thank you for participating in our survey.');
    push @page, show_survey_stats($sid);
  } else {
    # bummer -- unknown survey type or it is missing
  }

  print @page;
  print $q->end_html;
  return;
}


# Function: show_survey_stats
#
# For a poll/survey show statistics of what were participant responses
#
# Parameters:
# $sid - Survey ID
#
# Returns:
# A graph/table representing the histogram of responses
sub show_survey_stats ($) {
  my $sid    = shift;
  $survey    = read_survey(get_local_path($sid)) unless defined $survey;
  my $res    = read_survey_responses($sid);
  my @page;        # page struct
  my $p;
  my @comments;    # we will store the list of question IDs that are
                   # comments here for further processing
  my $compact = 0;

  push @page, $q->start_div({-class => 'surveyResults', -id => $sid});
  push @page, $q->h2($survey->{'description'});
  push @page, $q->p('Total responses collected: ', $res->{'g_total'}) unless $compact;

  foreach my $k ( sort keys %{$survey->{'question'}} ) {
    # If we come across a comment-type question, we store it's number
    # in a list and skip forward
    (push @comments, $k) && last if $survey->{'question'}->{$k}->{'type'} =~ /text|comment/;

    push @page, $q->h4($survey->{'question'}->{$k}->{'text'});
    push @page, $q->start_table({-class=>'results', -border=>0, -width=>'75%'});
    push @page, $q->Tr({ -class=>'head' }, th('Answers'),
                       th({-class=>'thRepl'},'Replies'),
                       th({-class=>'thPct'},'%/Total'),
                       th({-class=>'thGraph'},'')) unless $compact;
    my $ans = $survey->{'question'}->{$k}->{'answer'};
    my $rep = $res->{'resp'}->{$k}->{'a'};

    foreach my $a (sort keys %{$ans}) {
      $p = round( ($rep->{$a} / $res->{'resp'}->{$k}->{'total'} * 100), 2);
      if ($compact) {
	push @page, $q->Tr(td(shortened($res->{'question'}->{$k}->{'answer'}->{$a}->{'content'}, 4)),
                           td({-class=>'graph'}, bar($p)));
      } else {
	push @page, $q->Tr(td($a.'. '.$ans->{$a}->{'content'}),
                           td({-class=>'number'}, $rep->{$a} || '&nbsp;'),
                           td({-class=>'number'}, "${p}%"),
                           td({-class=>'graph'}, bar($p)));
      }
    }

    push @page, $q->Tr(th('Totals'),
                   th({-class=>'number'},$res->{'resp'}->{$k}->{'total'}),
                   th({-class=>'number'},'&nbsp;'),th('')) unless $compact;
    push @page, $q->end_table();
  }
  push @page, $q->end_div();

  if ( scalar @comments > 0 ) {
    push @page, h3('Participant comments');

    # Listing out comment-type replies
    push @page, start_div({-class=>'surveySnswers'});
    foreach my $k (@comments) {
      push @page, $q->h4($survey->{'question'}->{$k}->{'text'});
      my $a = $res->{'resp'}->{$k}->{'a'};
      #push @page, $q->pre(Dumper($a));
      my @li;
      map { push @li, $q->div(reformat($_)) } sort keys %{$a};
      push @page, $q->ul({-class=>'comments'}, @li);
    }
    push @page, $q->end_div();
  }

  return @page;
}

# Function: reformat(TXT)
#
# Poor-man's wiki engine.  Supported formatting:
#
#   - *bold* and _italics_
#   - single line break is treated as <br/>
#   - double line break creates a <p/>
#   - three spaces, followed by a minus (-) or an asterics (*) and a space create an <ul/>
#   - three spaces, followed by a number, followed by a dot and a space create an <ol/>
#   - list nesting is NOT supported
sub reformat($) {
  my $txt = shift;
  my @blocks = split qr%\\n\\n%, $txt;
  my @rtxt;
  foreach my $block (@blocks) {
    next if $block =~ /^$/;
	$block =~ s%\*([^ *][^*]+)\*%<strong>$1</strong>%g;
	$block =~ s%_([^_]+)_%<em>$1</em>%g;
	if ($block =~ /^\s{3}([-*]|\d+\.)\s/) {
	  my $tag = ( $1 =~ /\d/ ? 'ol' : 'ul' );
	  my $re = ( $tag eq 'ul' ? qr{[-*]} : qr{\d+\.} );
	  my $tmp;
	  map { $tmp .= "<li>$_</li>" unless $_ eq ''; } split qr%\s{3}$re\s%, $block;
	  $block = "\n<$tag>$tmp</$tag>\n";
	  $block =~ s%\\n%<br/>%g;
	} else {
	  $block =~ s%\\n%<br/>%g;
	  $block = "<p>$block</p>";
	}
	push @rtxt, $block;
  }  
  return join "\n",@rtxt;
}

# draw a bar
sub bar($) {
  my $width = shift;
  my $str = '&nbsp;';
  $width = $width * 3;  # arbitrary number, to make graph look better...
  return $q->div( {-class=>'bargraph'},
                  span({-class=>'bar',-style=>"width:${width}px;"},$str) );
}

# shorten text
sub shortened ($$) {
  my($s,$l) = @_;
  return substr($s,1,$l).'&helip;';
}

# Function form_extras
sub form_extras($) {
  my $sid = shift;
  my $js = "Form.getElements('$sid').each(function(s) { s.checked = false; });";
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
  print standard_headers('Survey Application Documentation');
  my @doc = <DATA>;
  print @doc;
  print $q->end_html;
}

# finish it
print $q->div(@pgdebug) if $debug;
my $end = (times)[0];
printf "<br/>Elapsed time: %.2f seconds!\n", $end - $start if $debug;
1;

__DATA__

<style type="text/css"><!--
#doc { margin:1em; width:50em; }
pre { font-size:0.8em; }
.syntax0 { color: #000000; }
.syntax1 { color: #cc0000; }
.syntax2 { color: #ff8400; }
.syntax3 { color: #6600cc; }
.syntax4 { color: #cc6600; }
.syntax5 { color: #ff0000; }
.syntax6 { color: #9966ff; }
.syntax7 { background: #ffffcc; color: #ff0066; }
.syntax8 { color: #006699; font-weight: bold; }
.syntax9 { color: #009966; font-weight: bold; }
.syntax10 { color: #0099ff; font-weight: bold; }
.syntax11 { color: #66ccff; font-weight: bold; }
.syntax12 { color: #02b902; }
.syntax13 { color: #ff00cc; }
.syntax14 { color: #cc00cc; }
.syntax15 { color: #9900cc; }
.syntax16 { color: #6600cc; }
.syntax17 { color: #0000ff; }
.syntax18 { color: #000000; font-weight: bold; }
.gutter { background: #dbdbdb; color: #000000; }
.gutterH { background: #dbdbdb; color: #990066; }
dt { margin-top:0.5em; margin-bottom:0.25em;font-weight:bold; }
--></style>

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

<pre><span class="syntax0"><span class="gutter"> 1:</span><span class="syntax10">&lt;?</span><span class="syntax10">xml</span><span class="syntax10"> </span><span class="syntax10">version=&quot;1.0&quot;</span><span class="syntax10"> </span><span class="syntax10">encoding=&quot;utf-8&quot;?</span><span class="syntax10">&gt;</span>
<span class="gutter"> 2:</span><span class="syntax17">&lt;</span><span class="syntax17">survey</span><span class="syntax17"> </span><span class="syntax17">id</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">sid200801</span><span class="syntax13">&quot;</span>
<span class="gutter"> 3:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">description</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">Trade</span><span class="syntax13"> </span><span class="syntax13">Finance</span><span class="syntax13"> </span><span class="syntax13">Assessment</span><span class="syntax13">&quot;</span>
<span class="gutter"> 4:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">validFrom</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">20080324</span><span class="syntax13">&quot;</span>
<span class="gutterH"> 5:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">validTill</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">20080430</span><span class="syntax13">&quot;</span>
<span class="gutter"> 6:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">surveyType</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">Assessment</span><span class="syntax13">&quot;</span>
<span class="gutter"> 7:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">protected</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">no</span><span class="syntax13">&quot;</span>
<span class="gutter"> 8:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">accessKey</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">&lt;secret_code_word&gt;</span><span class="syntax13">&quot;</span>
<span class="gutter"> 9:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">verboseResults</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">yes</span><span class="syntax13">&quot;</span>
<span class="gutterH">10:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">passRate</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">16</span><span class="syntax13">&quot;</span>
<span class="gutter">11:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">logUsers</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">yes</span><span class="syntax13">&quot;</span>
<span class="gutter">12:</span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17"> </span><span class="syntax17">active</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">yes</span><span class="syntax13">&quot;</span><span class="syntax17">&gt;</span>
<span class="gutter">13:</span>
<span class="gutter">14:</span>  <span class="syntax17">&lt;</span><span class="syntax17">surveyInstructions</span><span class="syntax17">&gt;</span>
<span class="gutterH">15:</span>  ...
<span class="gutter">16:</span>  <span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">surveyInstructions</span><span class="syntax17">&gt;</span>
<span class="gutter">17:</span>
<span class="gutter">18:</span>  <span class="syntax17">&lt;</span><span class="syntax17">question</span><span class="syntax17"> </span><span class="syntax17">key</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">1</span><span class="syntax13">&quot;</span><span class="syntax17"> </span><span class="syntax17">type</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">radio</span><span class="syntax13">&quot;</span><span class="syntax17"> </span><span class="syntax17">text</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">Which</span><span class="syntax13"> </span><span class="syntax13">is</span><span class="syntax13"> </span><span class="syntax13">not</span><span class="syntax13"> </span><span class="syntax13">a</span><span class="syntax13"> </span><span class="syntax13">type</span><span class="syntax13"> </span><span class="syntax13">of</span><span class="syntax13"> </span><span class="syntax13">Trade</span><span class="syntax13"> </span><span class="syntax13">Finance?</span><span class="syntax13">&quot;</span><span class="syntax17"> </span><span class="syntax17">answerKey</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">c</span><span class="syntax13">&quot;</span><span class="syntax17">&gt;</span>
<span class="gutter">19:</span>    <span class="syntax17">&lt;</span><span class="syntax17">answer</span><span class="syntax17"> </span><span class="syntax17">key</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">a</span><span class="syntax13">&quot;</span><span class="syntax17">&gt;</span>Trade Loans<span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">answer</span><span class="syntax17">&gt;</span>
<span class="gutterH">20:</span>    <span class="syntax17">&lt;</span><span class="syntax17">answer</span><span class="syntax17"> </span><span class="syntax17">key</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">b</span><span class="syntax13">&quot;</span><span class="syntax17">&gt;</span>Receivables Purchase<span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">answer</span><span class="syntax17">&gt;</span>
<span class="gutter">21:</span>    <span class="syntax17">&lt;</span><span class="syntax17">answer</span><span class="syntax17"> </span><span class="syntax17">key</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">c</span><span class="syntax13">&quot;</span><span class="syntax17">&gt;</span>Collections<span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">answer</span><span class="syntax17">&gt;</span>
<span class="gutter">22:</span>    <span class="syntax17">&lt;</span><span class="syntax17">answer</span><span class="syntax17"> </span><span class="syntax17">key</span><span class="syntax17">=</span><span class="syntax13">&quot;</span><span class="syntax13">d</span><span class="syntax13">&quot;</span><span class="syntax17">&gt;</span>Supplier Finance<span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">answer</span><span class="syntax17">&gt;</span>
<span class="gutter">23:</span>  <span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">question</span><span class="syntax17">&gt;</span>
<span class="gutter">24:</span><span class="syntax17">&lt;</span><span class="syntax17">/</span><span class="syntax17">survey</span><span class="syntax17">&gt;</span>
</span></pre>

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

